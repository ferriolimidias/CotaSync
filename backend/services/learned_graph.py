"""Data-driven planning primitives for learned action versions."""

from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import urlsplit
import json


def graph_metadata_available(action: dict[str, Any]) -> bool:
    states = action.get("learned_states")
    transitions = action.get("learned_transitions")
    return (
        action.get("execution_model") == "learned_graph"
        and isinstance(states, list)
        and isinstance(transitions, list)
        and bool(states)
        and bool(transitions)
        and all(isinstance(item, dict) and item.get("state_id") for item in states)
        and all(
            isinstance(item, dict)
            and (item.get("from_state_id") or item.get("from_state"))
            and (item.get("to_state_id") or item.get("to_state"))
            for item in transitions
        )
    )


def canonicalize_graph_metadata(action: dict[str, Any]) -> dict[str, Any]:
    """Collapse structurally identical states without changing learned steps."""
    result = dict(action)
    raw_states = action.get("learned_states")
    raw_transitions = action.get("learned_transitions")
    if not isinstance(raw_states, list) or not isinstance(raw_transitions, list):
        return result

    canonical_by_key: dict[str, str] = {}
    state_id_map: dict[str, str] = {}
    states: list[dict[str, Any]] = []
    for raw_state in raw_states:
        if not isinstance(raw_state, dict):
            continue
        old_id = str(raw_state.get("state_id") or "")
        if not old_id:
            continue
        signature = raw_state.get("signature") if isinstance(raw_state.get("signature"), dict) else {}
        stable_selectors = signature.get("stable_selectors")
        if not isinstance(stable_selectors, list):
            stable_selectors = []
        # Older graph versions used the current step selector as the only
        # marker. Keep it as matching evidence, but not as browser-state
        # identity: a fill/click changes the target while the page remains.
        structural_signature = dict(signature)
        legacy_markers = []
        if not stable_selectors:
            legacy_markers = [str(signature.get("selector") or "").strip()]
            structural_signature.pop("selector", None)
        structural_signature.pop("legacy_markers", None)
        key = json.dumps(
            {"page_ref": str(raw_state.get("page_ref") or "main"), "signature": structural_signature},
            sort_keys=True,
            ensure_ascii=False,
        )
        canonical_id = canonical_by_key.get(key)
        if canonical_id is None:
            canonical_id = old_id
            canonical_by_key[key] = canonical_id
            canonical_state = {**raw_state, "state_id": canonical_id}
            if legacy_markers:
                canonical_state["signature"] = {
                    **signature,
                    "legacy_markers": [marker for marker in legacy_markers if marker],
                }
            states.append(canonical_state)
        elif legacy_markers:
            existing = states[-1] if states and states[-1].get("state_id") == canonical_id else next(
                item for item in states if item.get("state_id") == canonical_id
            )
            existing_signature = existing.get("signature") if isinstance(existing.get("signature"), dict) else {}
            markers = list(existing_signature.get("legacy_markers") or [])
            for marker in legacy_markers:
                if marker and marker not in markers:
                    markers.append(marker)
            existing["signature"] = {**existing_signature, "legacy_markers": markers}
        state_id_map[old_id] = canonical_id

    transitions: list[dict[str, Any]] = []
    seen_transitions: set[tuple[str, str, int | str, str]] = set()
    for raw_transition in raw_transitions:
        if not isinstance(raw_transition, dict):
            continue
        source = str(raw_transition.get("from_state_id") or raw_transition.get("from_state") or "")
        target = str(raw_transition.get("to_state_id") or raw_transition.get("to_state") or "")
        source = state_id_map.get(source, source)
        target = state_id_map.get(target, target)
        step_index = raw_transition.get("step_index", "")
        key = (source, target, step_index, str(raw_transition.get("action_type") or ""))
        if not source or not target or key in seen_transitions:
            continue
        seen_transitions.add(key)
        transitions.append(
            {
                **raw_transition,
                "sequence_index": raw_transition.get("sequence_index", raw_transition.get("step_index", len(transitions))),
                "from_state": source,
                "to_state": target,
                "from_state_id": source,
                "to_state_id": target,
            }
        )

    outputs = []
    for raw_output in action.get("output_states") or []:
        if not isinstance(raw_output, dict):
            continue
        output = dict(raw_output)
        old_id = str(output.get("state_id") or "")
        if old_id:
            output["state_id"] = state_id_map.get(old_id, old_id)
        outputs.append(output)
    result["learned_states"] = states
    result["learned_transitions"] = transitions
    for steps_key in ("robust_steps", "passos_playwright"):
        raw_steps = action.get(steps_key)
        if not isinstance(raw_steps, list):
            continue
        remapped_steps = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                remapped_steps.append(raw_step)
                continue
            step = dict(raw_step)
            for key in ("before_state_id", "after_state_id", "graph_from_state_id"):
                if step.get(key):
                    step[key] = state_id_map.get(str(step[key]), str(step[key]))
            remapped_steps.append(step)
        result[steps_key] = remapped_steps
    if isinstance(action.get("output_states"), list):
        result["output_states"] = outputs
    return result


def _signature_score(observation: dict[str, Any], signature: dict[str, Any]) -> int:
    score = 0
    if observation.get("host") and observation.get("host") == signature.get("host"):
        score += 4
    if observation.get("path") and observation.get("path") == signature.get("path"):
        score += 3
    if observation.get("title") and signature.get("title") and observation["title"] == signature["title"]:
        score += 2
    raw_expected_selectors = signature.get("stable_selectors", [])
    if not isinstance(raw_expected_selectors, list):
        raw_expected_selectors = []
    expected_selectors = {str(item).strip() for item in raw_expected_selectors if str(item).strip()}
    legacy_markers = signature.get("legacy_markers", [])
    if isinstance(legacy_markers, list):
        expected_selectors.update(str(item).strip() for item in legacy_markers if str(item).strip())
    observed_selectors = set(observation.get("visible_selectors") or [])
    if expected_selectors:
        overlap = expected_selectors & observed_selectors
        score += min(8, len(overlap) * 2)
        if overlap and len(overlap) >= max(1, min(3, len(expected_selectors))):
            score += 3
    else:
        expected_selector = str(signature.get("selector") or "")
        if expected_selector and expected_selector in observed_selectors:
            score += 5
    return score


def match_observation_to_learned_state(
    observations: list[dict[str, Any]],
    states: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for observation in observations:
        for state in states:
            score = _signature_score(observation, state.get("signature") or {})
            if score:
                candidates.append({"state": state, "observation": observation, "score": score})
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        return {"status": "unknown", "reason": "unknown_browser_state", "candidates": []}
    top_score = candidates[0]["score"]
    top = [item for item in candidates if item["score"] == top_score]
    if len(top) > 1 and len({item["state"].get("state_id") for item in top}) > 1:
        return {"status": "ambiguous", "reason": "ambiguous_learned_state", "candidates": top}
    selected = candidates[0]
    return {
        "status": "matched",
        "state_id": selected["state"].get("state_id"),
        "page_ref": selected["state"].get("page_ref", "main"),
        "score": top_score,
        "evidence": selected["observation"],
        "candidates": candidates,
    }


def find_graph_path(
    transitions: list[dict[str, Any]],
    current_state_id: str,
    target_state_id: str,
) -> list[dict[str, Any]] | None:
    if current_state_id == target_state_id:
        return []
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for transition in transitions:
        adjacency.setdefault(
            str(transition.get("from_state_id") or transition.get("from_state") or ""),
            [],
        ).append(transition)
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(current_state_id, [])])
    visited = {current_state_id}
    while queue:
        state_id, path = queue.popleft()
        for transition in adjacency.get(state_id, []):
            next_state = str(transition.get("to_state_id") or transition.get("to_state") or "")
            if not next_state or next_state in visited:
                continue
            next_path = path + [transition]
            if next_state == target_state_id:
                return next_path
            visited.add(next_state)
            queue.append((next_state, next_path))
    return None


def ordered_graph_path(
    transitions: list[dict[str, Any]],
    current_state_id: str,
    target_state_id: str,
) -> list[dict[str, Any]] | None:
    """Plan the demonstrated sequence while retaining same-state transitions."""
    if current_state_id == target_state_id:
        return []
    ordered = sorted(
        (item for item in transitions if isinstance(item, dict)),
        key=lambda item: (
            int(item.get("sequence_index"))
            if str(item.get("sequence_index", "")).lstrip("-").isdigit()
            else int(item.get("step_index", 0) or 0),
        ),
    )
    path: list[dict[str, Any]] = []
    state_id = str(current_state_id)
    started = False
    for transition in ordered:
        source = str(transition.get("from_state_id") or transition.get("from_state") or "")
        target = str(transition.get("to_state_id") or transition.get("to_state") or "")
        if not started:
            if source != state_id:
                continue
            started = True
        elif source != state_id:
            return None
        if not target:
            return None
        path.append(transition)
        state_id = target
        if state_id == target_state_id:
            return path
    return None


def graph_target_state(action: dict[str, Any]) -> str:
    outputs = action.get("output_states")
    if isinstance(outputs, list):
        for output in outputs:
            if isinstance(output, dict) and output.get("state_id"):
                return str(output["state_id"])
    transitions = action.get("learned_transitions") or []
    return (
        str(transitions[-1].get("to_state_id") or transitions[-1].get("to_state") or "")
        if transitions and isinstance(transitions[-1], dict)
        else ""
    )


def transition_kind(transition: dict[str, Any]) -> str:
    """Return the learned semantic relation, never infer a branch from order."""
    explicit = str(transition.get("transition_kind") or "").strip().lower()
    if explicit in {"branch", "alternative"}:
        return "branch"
    if transition.get("branch_id") or transition.get("alternative_group") or transition.get("condition"):
        return "branch"
    return "sequence"


def branch_candidates(transitions: list[dict[str, Any]], state_id: str) -> list[dict[str, Any]]:
    """List explicitly learned alternatives from a structural state.

    Consecutive same-state transitions remain sequence edges. They are not
    alternatives merely because they share a source state.
    """
    return [
        item for item in transitions
        if isinstance(item, dict)
        and str(item.get("from_state_id") or item.get("from_state") or "") == str(state_id)
        and transition_kind(item) == "branch"
    ]


def transition_satisfied(
    transition: dict[str, Any],
    step: dict[str, Any],
    *,
    current_value: str | None = None,
    expected_value: str | None = None,
) -> bool:
    """Check only deterministic facts available for reentry."""
    action_type = str(transition.get("action_type") or step.get("tipo") or "").strip().lower()
    if action_type in {"preencher", "fill", "selecionar", "select"}:
        return current_value is not None and expected_value is not None and current_value == expected_value
    return False


async def observe_browser_pages(context: Any, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect deterministic evidence from every open page for graph matching."""
    selector_by_state: dict[str, set[str]] = {}
    for state in states:
        signature = state.get("signature") if isinstance(state, dict) else {}
        selectors = (signature or {}).get("stable_selectors") or []
        if not isinstance(selectors, list):
            selectors = []
        output_selector = str((signature or {}).get("output_selector") or "").strip()
        if output_selector:
            selectors = [*selectors, output_selector]
        if not selectors:
            selector = str((signature or {}).get("selector") or "")
            selectors = [selector] if selector else []
        selectors.extend((signature or {}).get("legacy_markers") or [])
        for selector in selectors:
            if selector:
                selector_by_state.setdefault(str(state.get("page_ref") or "main"), set()).add(str(selector))
    observations: list[dict[str, Any]] = []
    for page in [item for item in getattr(context, "pages", []) if not item.is_closed()]:
        url = str(getattr(page, "url", "") or "")
        parsed = urlsplit(url)
        try:
            title = (await page.title()).strip()[:200]
        except Exception:
            title = ""
        visible_selectors: list[str] = []
        for selectors in selector_by_state.values():
            for selector in selectors:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible():
                        visible_selectors.append(selector)
                except Exception:
                    continue
        observations.append(
            {
                "page": page,
                "host": str(parsed.hostname or "").lower(),
                "path": str(parsed.path or "/"),
                "title": title,
                "visible_selectors": visible_selectors,
            }
        )
    return observations


def graph_step_indices(path: list[dict[str, Any]]) -> list[int]:
    return [int(item["step_index"]) for item in path if str(item.get("step_index", "")).lstrip("-").isdigit()]
