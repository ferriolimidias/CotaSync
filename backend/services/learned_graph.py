"""Data-driven planning primitives for learned action versions."""

from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import urlsplit


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


def _signature_score(observation: dict[str, Any], signature: dict[str, Any]) -> int:
    score = 0
    if observation.get("host") and observation.get("host") == signature.get("host"):
        score += 4
    if observation.get("path") and observation.get("path") == signature.get("path"):
        score += 3
    if observation.get("title") and signature.get("title") and observation["title"] == signature["title"]:
        score += 2
    expected_selector = str(signature.get("selector") or "")
    if expected_selector and expected_selector in set(observation.get("visible_selectors") or []):
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


async def observe_browser_pages(context: Any, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect deterministic evidence from every open page for graph matching."""
    selector_by_state: dict[str, set[str]] = {}
    for state in states:
        signature = state.get("signature") if isinstance(state, dict) else {}
        selector = str((signature or {}).get("selector") or "")
        if selector:
            selector_by_state.setdefault(str(state.get("page_ref") or "main"), set()).add(selector)
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
