from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from langchain_openai import ChatOpenAI

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.services.action_runner import (
    finish_action_run,
    missing_required_variables,
    start_action_run,
)
from backend.services.actions_repository import default_ui_map_path
from backend.services.extraction_targets import (
    extract_value_near_label,
    friendly_extraction_label,
    normalize_label_key,
)
from backend.services.runs_repository import update_run

logger = logging.getLogger("cotasync.action_validation_review")

_MAX_FINAL_TEXT_CHARS = 12000
_MAX_FINAL_DOM_CHARS = 30000


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_ui_map(path: Path | None = None) -> dict[str, Any]:
    ui_map_path = path or default_ui_map_path()
    if not ui_map_path.is_file():
        return {"acoes_conhecidas": {}}
    payload = json.loads(ui_map_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("data/ui_map.json deve conter um objeto JSON.")
    if not isinstance(payload.get("acoes_conhecidas"), dict):
        payload["acoes_conhecidas"] = {}
    return payload


def _save_ui_map(payload: dict[str, Any], path: Path | None = None) -> None:
    ui_map_path = path or default_ui_map_path()
    ui_map_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=ui_map_path.parent, delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, ui_map_path)


def _raw_action(action: ActionDetail, path: Path | None = None) -> dict[str, Any]:
    payload = _load_ui_map(path)
    actions = payload.get("acoes_conhecidas", {})
    raw = actions.get(action.key) if isinstance(actions, dict) else None
    return raw if isinstance(raw, dict) else {}


def _example_variables(raw_action: dict[str, Any]) -> dict[str, Any]:
    examples: dict[str, Any] = {}
    steps = raw_action.get("passos_playwright") or []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            key = str(step.get("variavel") or "").strip()
            value = step.get("example_value")
            if key and value not in (None, ""):
                examples[key] = value
    raw_events = raw_action.get("learning_events")
    events = raw_events if isinstance(raw_events, list) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        key = str(event.get("variable_key") or "").strip()
        value = event.get("example_value")
        if key and value not in (None, ""):
            examples[key] = value
    return examples


def validation_variables(action: ActionDetail, supplied: dict[str, Any], raw_action: dict[str, Any]) -> dict[str, Any]:
    variables = dict(_example_variables(raw_action))
    variables.update(supplied if isinstance(supplied, dict) else {})
    return variables


def _clean_text(value: Any, *, limit: int = 1000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"([?&](?:token|key|secret|password|senha)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"((?:token|secret|password|senha|authorization|cookie)\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
    return text[:limit]


def _target_request(raw_action: dict[str, Any], action: ActionDetail) -> str:
    extraction_target = str(raw_action.get("extraction_target") or action.extraction_target or "").strip()
    expected = str(raw_action.get("expected_result") or action.expected_result or "").strip()
    objective = str(raw_action.get("objective") or action.objective or "").strip()
    for value in (extraction_target, expected, objective):
        if value:
            return value
    targets = raw_action.get("extraction_targets") if isinstance(raw_action.get("extraction_targets"), list) else []
    return str(targets[0]).strip() if targets else action.name


def _visible_lines(final_text: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\r\n]+| {2,}", str(final_text or "")):
        line = _clean_text(raw, limit=500)
        if not line:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= 180:
            break
    return lines


def _candidate_pairs(final_text: str) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for line in _visible_lines(final_text):
        match = re.match(r"(?P<label>[A-Za-zÀ-ÿ0-9 ._/()-]{2,80})\s*[:\-–—]\s*(?P<value>.{1,120})$", line)
        if not match:
            continue
        label = _clean_text(match.group("label"), limit=120)
        value = _clean_text(match.group("value"), limit=160)
        if label and value and normalize_label_key(label) != normalize_label_key(value):
            pairs.append({"label": label, "value": value, "source": "visible_text_pair"})
        if len(pairs) >= 40:
            break
    return pairs


def build_extraction_candidates(
    action: ActionDetail,
    raw_action: dict[str, Any],
    result_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    payload = result_payload if isinstance(result_payload, dict) else {}
    final_text = str(payload.get("final_page_text") or "")
    final_dom = str(payload.get("final_page_dom") or "")
    target = _target_request(raw_action, action)
    candidates: list[dict[str, Any]] = []
    for label in [target, str(raw_action.get("extraction_target") or ""), *list(raw_action.get("extraction_targets") or [])]:
        label = str(label or "").strip()
        if not label:
            continue
        value = extract_value_near_label(final_dom, label) or extract_value_near_label(final_text, label)
        if value:
            candidates.append(
                {
                    "kind": "near_label",
                    "label": label,
                    "value": _clean_text(value, limit=160),
                    "confidence": "high",
                }
            )
    for pair in _candidate_pairs(final_text):
        candidates.append({"kind": "label_value_pair", **pair})
    extracted = payload.get("dados_extraidos")
    extracted_items = extracted.items() if isinstance(extracted, dict) else []
    for key, value in extracted_items:
        candidates.insert(
            0,
            {
                "kind": "existing_extraction",
                "label": _clean_text(key, limit=120),
                "value": _clean_text(value, limit=160),
                "confidence": "high",
            },
        )
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = (
            str(candidate.get("kind") or ""),
            normalize_label_key(candidate.get("label") or ""),
            str(candidate.get("value") or "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if len(unique) >= 60:
            break
    return unique


def _short_steps(raw_action: dict[str, Any]) -> list[dict[str, Any]]:
    steps = raw_action.get("robust_steps") or raw_action.get("passos_playwright") or []
    if not isinstance(steps, list):
        return []
    return [
        {
            "index": index,
            "type": str(step.get("tipo") or ""),
            "selector": str(step.get("seletor") or "")[:240],
            "variable": str(step.get("variavel") or ""),
            "target_text": str(step.get("target_text") or "")[:160],
        }
        for index, step in enumerate(steps)
        if isinstance(step, dict)
    ][:120]


def _safe_step_trace(result_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = result_payload if isinstance(result_payload, dict) else {}
    trace = payload.get("step_trace")
    if not isinstance(trace, list):
        return []
    return [item for item in trace if isinstance(item, dict)][:160]


def _default_summary_instruction(target: str, label: str, output_type: str) -> str:
    if "arquivo" in output_type.casefold() or "pdf" in output_type.casefold():
        return "Retorne o arquivo baixado e uma frase curta confirmando que o download foi gerado."
    readable = label or target or "resultado solicitado"
    return f"Retorne somente o valor encontrado para '{readable}'. Não inclua outros dados da tela."


def _fallback_overlay(
    *,
    action: ActionDetail,
    raw_action: dict[str, Any],
    run: RunRecord,
    candidates: list[dict[str, Any]],
    status: str = "needs_attention",
    reason: str = "ai_unavailable",
) -> dict[str, Any]:
    target = _target_request(raw_action, action)
    best = candidates[0] if candidates else {}
    label = str(best.get("label") or raw_action.get("extraction_target") or target).strip()
    value = str(best.get("value") or "").strip()
    output_type = str(raw_action.get("output_type") or action.output_type or "")
    summary_instruction = _default_summary_instruction(target, label, output_type)
    return {
        "review_status": status,
        "reviewed_at": _utc_now_iso(),
        "review_run_id": run.id,
        "target_user_request": target,
        "extraction": {
            "target_label_user": target,
            "screen_label": label,
            "selector_hint": str(best.get("selector") or best.get("best_selector") or ""),
            "nearby_text": label,
            "value_pattern": "valor próximo ao rótulo solicitado",
            "return_format": "somente o valor",
            "expected_example": value,
        },
        "summary_instruction": summary_instruction,
        "waits": [],
        "risks": [] if status == "approved" else [reason],
        "notes": [f"Revisão determinística: {reason}."],
    }


def _json_from_ai_response(value: Any) -> dict[str, Any]:
    text = str(getattr(value, "content", value) or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        parsed = json.loads(match.group(0)) if match else {}
    return parsed if isinstance(parsed, dict) else {}


async def _ai_review(payload: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    prompt = (
        "Você é o revisor de aprendizado do CotaSync. A IA não pode navegar, clicar ou alterar passos; "
        "ela apenas observa o replay real já executado e propõe uma camada reviewed_overlay. "
        "Responda somente JSON no formato solicitado, sem cadeia de pensamento. "
        "Payload estruturado: "
        + json.dumps(payload, ensure_ascii=False)
    )
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    response = await ChatOpenAI(
        model=model,
        temperature=0,
        api_key=api_key,
        timeout=12,
        max_retries=0,
    ).ainvoke(prompt)
    parsed = _json_from_ai_response(response)
    return parsed or None


def _overlay_from_ai(
    *,
    action: ActionDetail,
    raw_action: dict[str, Any],
    run: RunRecord,
    ai_review: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    target = _target_request(raw_action, action)
    status = str(ai_review.get("review_status") or "needs_attention").strip()
    if status not in {"approved", "needs_attention", "failed"}:
        status = "needs_attention"
    best_label = str(ai_review.get("best_label") or raw_action.get("extraction_target") or target).strip()
    best_value = str(ai_review.get("best_value_example") or "").strip()
    if not best_value and candidates:
        best_value = str(candidates[0].get("value") or "")
    output_type = str(raw_action.get("output_type") or action.output_type or "")
    summary_instruction = str(ai_review.get("summary_instruction") or "").strip() or _default_summary_instruction(
        target,
        best_label,
        output_type,
    )
    return {
        "review_status": status,
        "reviewed_at": _utc_now_iso(),
        "review_run_id": run.id,
        "target_user_request": target,
        "extraction": {
            "target_label_user": target,
            "screen_label": best_label,
            "selector_hint": str(ai_review.get("best_selector") or ""),
            "nearby_text": best_label,
            "value_pattern": str(ai_review.get("value_pattern") or "valor próximo ao rótulo"),
            "return_format": str(ai_review.get("return_format") or "somente o valor"),
            "expected_example": best_value,
        },
        "summary_instruction": summary_instruction,
        "waits": ai_review.get("wait_suggestions", []) if isinstance(ai_review.get("wait_suggestions"), list) else [],
        "selector_alternatives": (
            ai_review.get("selector_alternatives", [])
            if isinstance(ai_review.get("selector_alternatives"), list)
            else []
        ),
        "risks": ai_review.get("risks", []) if isinstance(ai_review.get("risks"), list) else [],
        "notes": [str(ai_review.get("reasoning_summary") or "").strip()][:1],
    }


def _save_review_overlay(
    action: ActionDetail,
    run: RunRecord,
    overlay: dict[str, Any],
    *,
    ai_review_summary: str = "",
    extraction_candidates: list[dict[str, Any]] | None = None,
    path: Path | None = None,
) -> None:
    payload = _load_ui_map(path)
    actions = payload["acoes_conhecidas"]
    raw = actions.get(action.key)
    if not isinstance(raw, dict):
        raise RuntimeError("Acao nao encontrada em data/ui_map.json para salvar reviewed_overlay.")
    raw["review_status"] = str(overlay.get("review_status") or "needs_attention")
    raw["review_last_run_id"] = run.id
    raw["reviewed_overlay"] = overlay
    raw["ai_review_summary"] = ai_review_summary or "Revisão do replay real concluída."
    raw["final_summary_instruction"] = str(overlay.get("summary_instruction") or "")
    raw["extraction_review"] = overlay.get("extraction") if isinstance(overlay.get("extraction"), dict) else {}
    raw["ai_reviewed"] = bool(raw.get("ai_reviewed", False))
    if extraction_candidates is not None:
        raw["last_validation_extraction_candidates"] = extraction_candidates
    actions[action.key] = raw
    _save_ui_map(payload, path)


def _mark_failed_review(action: ActionDetail, run: RunRecord, raw_action: dict[str, Any]) -> dict[str, Any]:
    diagnostics = run.result_payload if isinstance(run.result_payload, dict) else {}
    overlay = {
        "review_status": "failed",
        "reviewed_at": _utc_now_iso(),
        "review_run_id": run.id,
        "target_user_request": _target_request(raw_action, action),
        "extraction": {},
        "summary_instruction": "",
        "waits": [],
        "risks": [_clean_text(diagnostics.get("reason") or run.error_message or "validation_failed", limit=400)],
        "notes": ["O replay real falhou; o mapa mecânico foi preservado e o overlay não foi aprovado."],
        "diagnostics": diagnostics,
    }
    _save_review_overlay(
        action,
        run,
        overlay,
        ai_review_summary="Validação falhou durante o replay real.",
    )
    return overlay


async def review_finished_validation_run(
    action: ActionDetail,
    run: RunRecord,
    raw_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = raw_action if isinstance(raw_action, dict) else _raw_action(action)
    if run.status != "success":
        overlay = _mark_failed_review(action, run, raw)
    else:
        payload = run.result_payload if isinstance(run.result_payload, dict) else {}
        candidates = build_extraction_candidates(action, raw, payload)
        review_payload = {
            "action_name": action.name,
            "target_user_request": _target_request(raw, action),
            "visible_label_hint": raw.get("extraction_target") or action.extraction_target or "",
            "variables": [
                {"key": variable.key, "label": variable.label, "required": variable.required}
                for variable in action.variables
            ],
            "steps_summary": _short_steps(raw),
            "step_trace": _safe_step_trace(payload),
            "extraction_candidates": candidates,
            "final_text": _clean_text(payload.get("final_page_text"), limit=_MAX_FINAL_TEXT_CHARS),
            "final_dom_excerpt": _clean_text(payload.get("final_page_dom"), limit=_MAX_FINAL_DOM_CHARS),
            "final_page": payload.get("final_page") if isinstance(payload.get("final_page"), dict) else {},
            "screenshot": {
                "path": str(payload.get("screenshot_path") or payload.get("evidencia") or ""),
            },
            "downloaded_files": payload.get("downloaded_files", []),
            "main_file": payload.get("main_file", {}),
            "required_json_response": {
                "review_status": "approved|needs_attention|failed",
                "extraction_target_confirmed": "boolean",
                "best_label": "string",
                "best_selector": "string",
                "best_value_example": "string",
                "return_format": "string",
                "summary_instruction": "string",
                "wait_suggestions": [],
                "selector_alternatives": [],
                "risks": [],
                "reasoning_summary": "curto",
            },
        }
        try:
            ai_result = await _ai_review(review_payload)
        except Exception as exc:
            logger.info("Revisao IA indisponivel: %s", type(exc).__name__)
            ai_result = None
        overlay = (
            _overlay_from_ai(action=action, raw_action=raw, run=run, ai_review=ai_result, candidates=candidates)
            if isinstance(ai_result, dict)
            else _fallback_overlay(action=action, raw_action=raw, run=run, candidates=candidates)
        )
        ai_summary = (
            str(ai_result.get("reasoning_summary") or "").strip()
            if isinstance(ai_result, dict)
            else "Revisão determinística gerada porque a IA não estava disponível."
        )
        _save_review_overlay(
            action,
            run,
            overlay,
            ai_review_summary=ai_summary,
            extraction_candidates=candidates,
        )
        if isinstance(run.result_payload, dict):
            run.result_payload["validation_review"] = True
            run.result_payload["extraction_candidates"] = candidates
            run.result_payload["reviewed_overlay"] = overlay
            update_run(run)
    return overlay


async def run_validation_review(action: ActionDetail, request: ActionRunRequest) -> RunRecord:
    raw = _raw_action(action)
    variables = validation_variables(action, request.variables, raw)
    replay_request = request.model_copy(update={"variables": variables, "requested_by": request.requested_by or "validation_review"})
    missing = missing_required_variables(action, replay_request.variables)
    if missing:
        raise ValueError(json.dumps({"missing_variables": missing}, ensure_ascii=False))
    run = start_action_run(action, replay_request, run_type="validation_review")
    try:
        run.result_payload = run.result_payload or {}
        run.result_payload["validation_review"] = True
        update_run(run)
    except Exception:
        pass
    run = await finish_action_run(action, replay_request, run)
    await review_finished_validation_run(action, run, raw)
    return run


def schedule_validation_review(action: ActionDetail, request: ActionRunRequest) -> RunRecord:
    raw = _raw_action(action)
    variables = validation_variables(action, request.variables, raw)
    replay_request = request.model_copy(update={"variables": variables, "requested_by": request.requested_by or "validation_review"})
    missing = missing_required_variables(action, replay_request.variables)
    if missing:
        raise ValueError(json.dumps({"missing_variables": missing}, ensure_ascii=False))
    run = start_action_run(action, replay_request, run_type="validation_review")
    run.result_payload = {"validation_review": True}
    update_run(run)

    async def _background() -> None:
        finished = await finish_action_run(action, replay_request, run)
        await review_finished_validation_run(action, finished, raw)

    asyncio.create_task(_background())
    return run
