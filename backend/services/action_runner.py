from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.agente import executar_acao_fast_track
from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.services.action_pages import validate_action_page_url
from backend.services.operational_summary import build_operational_summary_result, build_technical_summary
from backend.services.runs_repository import append_run, update_run

logger = logging.getLogger("cotasync.action_runner")

_SENSITIVE_KEYS = {
    "authorization",
    "bearer",
    "celular",
    "cnpj",
    "cookie",
    "cpf",
    "email",
    "key",
    "password",
    "phone",
    "secret",
    "senha",
    "telefone",
    "token",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def missing_required_variables(action: ActionDetail, variables: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for variable in action.variables:
        if not variable.required:
            continue
        value = variables.get(variable.key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(variable.key)
    return missing


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(part in lowered for part in _SENSITIVE_KEYS)


def _mask_scalar(value: Any, *, reveal_last: int = 4) -> str:
    text = str(value)
    if not text:
        return ""
    if len(text) <= reveal_last:
        return "*" * len(text)
    return f"{'*' * (len(text) - reveal_last)}{text[-reveal_last:]}"


def mask_value_for_key(key: str, value: Any) -> Any:
    if not _is_sensitive_key(key):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return "[valor estruturado omitido]"

    reveal_last = 2 if str(key or "").lower() == "cpf" else 4
    return _mask_scalar(value, reveal_last=reveal_last)


def mask_variables(variables: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, value in variables.items():
        masked[str(key)] = mask_value_for_key(str(key), value)
    return masked


def _safe_runtime_file_metadata(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    path = str(value.get("path") or "").replace("\\", "/").strip()
    if not path.startswith("data/runs/downloads/") or ".." in path.split("/"):
        return None
    return {
        "name": str(value.get("name") or "arquivo")[:200],
        "path": path[:500],
        "mime_type": str(value.get("mime_type") or "application/octet-stream")[:100],
        "size_bytes": max(0, int(value.get("size_bytes") or 0)),
    }


def _safe_legacy_file_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    safe: list[str] = []
    for raw in value:
        path = str(raw or "").replace("\\", "/").strip()
        if ".." in path.split("/") or path.startswith("/"):
            continue
        if path.startswith(("downloads/", "data/runs/downloads/")):
            safe.append(path[:500])
    return safe


def _safe_result_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    for key in (
        "evidencia",
        "arquivos",
        "downloaded_files",
        "main_file",
        "dados_extraidos",
        "passos_executados",
        "session_revalidated",
        "selector_diagnostics",
        "final_page",
    ):
        value = result.get(key)
        if value:
            if key == "dados_extraidos" and isinstance(value, dict):
                payload[key] = {
                    str(item_key): mask_value_for_key(str(item_key), item)
                    for item_key, item in value.items()
                }
            elif key == "arquivos":
                payload[key] = _safe_legacy_file_paths(value)
            elif key == "downloaded_files" and isinstance(value, list):
                payload[key] = [
                    item for raw in value if (item := _safe_runtime_file_metadata(raw)) is not None
                ]
            elif key == "main_file":
                safe_file = _safe_runtime_file_metadata(value)
                if safe_file is not None:
                    payload[key] = safe_file
            else:
                payload[key] = value
    return payload or None


def _safe_error_message(exc: Exception) -> str:
    text = re.sub(
        r"([?&](?:token|key|secret|password|senha)=)[^&\s]+",
        r"\1[REDACTED]",
        str(exc),
        flags=re.I,
    )
    text = re.sub(r"((?:token|secret|password|senha)\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
    return text[:1000] or type(exc).__name__


def _is_local_fixture(action: ActionDetail) -> bool:
    return action.test_mode or str(action.execution_type or "").lower() == "local_fixture"


def _run_local_fixture(action: ActionDetail, variables: dict[str, Any]) -> dict[str, Any]:
    echo = {variable.key: mask_value_for_key(variable.key, variables.get(variable.key)) for variable in action.variables}
    return {"echo": echo, "fixture": True, "action_id": action.id}


def _validate_desktop_result(action: ActionDetail, result: dict[str, Any]) -> None:
    if str(action.browser_mode or "browserless").strip() != "desktop_browser":
        return
    final_page = result.get("final_page")
    final_url = final_page.get("url") if isinstance(final_page, dict) else ""
    validate_action_page_url(action, final_url)


async def run_action_sync(action: ActionDetail, request: ActionRunRequest) -> RunRecord:
    created_at = utc_now_iso()
    run = RunRecord(
        id=str(uuid4()),
        action_id=action.id,
        action_key=action.key,
        status="pending",
        mode=request.mode,
        requested_by=request.requested_by.strip() or "api",
        session_id=request.session_id,
        created_at=created_at,
        variables=mask_variables(request.variables),
    )
    append_run(run)

    run.status = "running"
    run.started_at = utc_now_iso()
    update_run(run)

    try:
        if _is_local_fixture(action):
            run.status = "success"
            run.result_payload = _run_local_fixture(action, request.variables)
        elif action.steps_count <= 0:
            raise RuntimeError("Acao aprendida nao possui passos para execucao.")
        elif request.session_id:
            from backend.services.demo_session import demo_session_manager

            result = await demo_session_manager.execute_action(
                request.session_id,
                action.key,
                request.variables,
                run.id,
            )
            _validate_desktop_result(action, result)
            run.status = "success"
            run.result_payload = _safe_result_payload(result)
        else:
            result = await executar_acao_fast_track(action.key, request.variables, run.id)
            text = str(result.get("texto") or "").strip()
            execution_status = str(result.get("status") or "").strip().lower()
            if execution_status == "error" or text.startswith("❌") or "Falha" in text or "falha" in text:
                execution_error = RuntimeError(
                    str(result.get("error_message") or text or "Falha na execucao da acao.")
                )
                page_diagnostics = result.get("page_diagnostics")
                if isinstance(page_diagnostics, dict):
                    execution_error.diagnostics = page_diagnostics  # type: ignore[attr-defined]
                raise execution_error

            _validate_desktop_result(action, result)
            run.status = "success"
            run.result_payload = _safe_result_payload(result)
    except Exception as exc:
        safe_error = _safe_error_message(exc)
        logger.info("Run %s finalizada com erro do tipo %s", run.id, type(exc).__name__)
        run.status = "error"
        run.error_message = safe_error
        diagnostics = getattr(exc, "diagnostics", None)
        run.result_payload = {"selector_diagnostics": [diagnostics]} if isinstance(diagnostics, dict) else None
    finally:
        summary_result = await build_operational_summary_result(
            action,
            status=run.status,
            result_payload=run.result_payload,
            error_message=run.error_message,
        )
        run.operational_summary = summary_result.summary
        run.result_summary = run.operational_summary
        run.ai_summary_used = summary_result.ai_summary_used
        run.summary_source = summary_result.summary_source
        run.summary_reason = summary_result.summary_reason
        executed_steps = 0
        if isinstance(run.result_payload, dict):
            executed_steps = int(run.result_payload.get("passos_executados") or 0)
        run.technical_summary = build_technical_summary(
            status=run.status,
            executed_steps=executed_steps,
            result_payload=run.result_payload,
        )
        run.finished_at = utc_now_iso()
        update_run(run)

    return run
