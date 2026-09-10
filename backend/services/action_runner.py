from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.db import Action as DbAction, ActionVersion, Batch as DbBatch, Client, ClientList, ExternalAccessProfile, ExternalSystem, Run as DbRun, SessionLocal
from backend.services.action_pages import expected_action_hosts, validate_action_page_url
from backend.services.actions_repository import enrich_action_access_profile
from backend.services.learned_graph import canonicalize_graph_metadata
from backend.services.operational_summary import build_operational_summary_result, build_technical_summary
from backend.services.runtime_wait import RuntimeWaitCancelled
from backend.services.run_timeline import RunTimeline
from backend.services.runs_repository import (
    append_run,
    persist_terminal_run_fallback,
    update_run,
)

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


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Keep browser diagnostics persistable without leaking Playwright objects."""
    if depth > 12:
        return "[diagnostic depth limit]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        url = getattr(value, "url", None)
        if isinstance(url, str):
            return {"type": type(value).__name__, "url": url[:1000]}
        return f"[{type(value).__name__}]"


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
        "run_id",
        "action_id",
        "action_key",
        "evidencia",
        "arquivos",
        "downloaded_files",
        "main_file",
        "dados_extraidos",
        "passos_executados",
        "session_revalidated",
        "selector_diagnostics",
        "step_diagnostics",
        "step_trace",
        "step_index",
        "step_type",
        "step_selector",
        "step_value_template",
        "step_variable_key",
        "final_page",
        "final_page_text",
        "final_page_dom",
        "input_variables",
        "variables_used",
        "session_state",
        "reentry_strategy",
        "target_workflow_state",
        "recovery_attempts",
        "recovery_steps",
        "recovery_attempted",
        "operator_action_required",
        "last_page_title",
        "page_title",
        "current_host",
        "current_url",
        "query_completed_for",
        "query_result_confirmed",
        "query_transition_confirmed",
        "query_transition_step_index",
        "output_provenance",
        "graph_plan",
        "passos_pulados",
        "screenshot_path",
        "checkpoint_diagnostics",
        "next_step_index",
        "next_step_type",
        "next_step_selector",
        "next_step_url_before",
        "next_step_host_before",
        "next_step_expected_selector",
        "next_step_expected_url_or_host",
        "next_step_expected_text",
        "whether_next_step_was_microsoft_click",
        "learned_microsoft_step_compatible",
        "next_step_selector_count",
        "next_step_selector_visible",
        "next_step_text_count",
        "next_step_text_visible",
        "matched_by",
        "evidence",
        "retryable",
        "reason",
        "exception_type",
        "exception_message",
        "browser_mode",
        "runner",
        "whether_desktop_browser_used",
        "last_successful_step_index",
        "diagnostics",
        "validation_review",
        "extraction_candidates",
        "extraction_attention",
        "reviewed_overlay",
    ):
        value = result.get(key)
        if value is not None and value != [] and value != {}:
            if key == "dados_extraidos" and isinstance(value, dict):
                payload[key] = {
                    str(item_key): mask_value_for_key(str(item_key), item)
                    for item_key, item in value.items()
                }
            elif key == "input_variables" and isinstance(value, dict):
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
                payload[key] = _json_safe(value)
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
    if os.getenv("COTASYNC_ENABLE_SLOW_FIXTURE", "").strip().lower() in {"1", "true", "yes"}:
        sleep_seconds = max(0.0, min(float(variables.get("__sleep_seconds") or 0), 30.0))
        if sleep_seconds:
            time.sleep(sleep_seconds)
    echo = {variable.key: mask_value_for_key(variable.key, variables.get(variable.key)) for variable in action.variables}
    return {"echo": echo, "fixture": True, "action_id": action.id}


def _validate_desktop_result(action: ActionDetail, result: dict[str, Any]) -> None:
    if str(action.browser_mode or "desktop_browser").strip() != "desktop_browser":
        return
    if not expected_action_hosts(action):
        return
    final_page = result.get("final_page")
    final_url = final_page.get("url") if isinstance(final_page, dict) else ""
    validate_action_page_url(action, final_url)


def _is_desktop_learned_action(action: ActionDetail) -> bool:
    learning_mode = str(action.learning_mode or "").strip().casefold()
    return bool(
        str(action.browser_mode or "").strip() == "desktop_browser"
        or "desktop_browser" in learning_mode
    )


def _runtime_cancellation_probe(run_id: str, batch_id: str | None) -> Any:
    async def probe() -> bool:
        with SessionLocal() as session:
            if session.get(DbRun, str(run_id)) is not None:
                run_row = session.get(DbRun, str(run_id))
                if run_row and run_row.status in {"cancel_requested", "cancelled"}:
                    return True
            if batch_id:
                batch = session.get(DbBatch, str(batch_id))
                return bool(batch and (batch.cancel_requested or batch.status in {"cancel_requested", "cancelled"}))
            return False

    return probe


def _load_action_config(action: ActionDetail) -> dict[str, Any]:
    try:
        with SessionLocal() as session:
            db_action = session.query(DbAction).filter(DbAction.id == action.id).first()
            if db_action is not None and db_action.published_version_id:
                version = session.get(ActionVersion, db_action.published_version_id)
                if version is not None:
                    raw = dict(version.definition or {})
                    raw.setdefault("action_version_id", version.id)
                    raw.setdefault("nome_amigavel", db_action.name)
                    raw.setdefault("descricao", db_action.description)
                    raw.setdefault("required_access_profile_id", version.required_access_profile_id or db_action.required_access_profile_id)
                    raw.setdefault("run_start_strategy", version.run_start_strategy or "persistent_graph_reentry")
                    if version.run_start_strategy == "external_entry_each_run":
                        system = session.query(ExternalSystem).order_by(ExternalSystem.updated_at.desc()).first()
                        if system is not None:
                            raw.setdefault("entry_url", str((system.config or {}).get("entry_url") or ""))
                            raw.setdefault("external_system_id", system.id)
                    profile_id = str(raw.get("required_access_profile_id") or "").strip()
                    if profile_id:
                        profile = session.get(ExternalAccessProfile, profile_id)
                        if profile is not None:
                            raw.setdefault("access_profile_name", profile.display_name)
                            raw.setdefault("access_profile_email_or_identifier", profile.login_identifier)
                            raw.setdefault("microsoft_saved_account_identifier", profile.login_identifier)
                            raw.setdefault("external_system_id", profile.external_system_id)
                    enriched = enrich_action_access_profile(raw)
                    if enriched.get("execution_model") == "learned_graph":
                        enriched = canonicalize_graph_metadata(enriched)
                    return enriched
    except Exception:
        logger.exception("Falha ao carregar acao publicada do PostgreSQL.")
        return {}
    return {}


def _action_steps(action_config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = action_config.get("robust_steps") or action_config.get("passos_playwright") or []
    return [step for step in raw_steps if isinstance(step, dict)] if isinstance(raw_steps, list) else []


async def _run_desktop_browser_replay(
    action: ActionDetail,
    variables: dict[str, Any],
    run_id: str,
    *,
    batch_id: str | None = None,
    progress_callback: Any | None = None,
    timeline_callback: Any | None = None,
) -> dict[str, Any]:
    from backend.motor_browser import executar_acao_rapida

    action_config = _load_action_config(action)
    if not action_config:
        raise RuntimeError("Acao publicada nao encontrada no PostgreSQL.")
    action_config["browser_mode"] = "desktop_browser"
    steps = _action_steps(action_config)
    if not steps:
        raise RuntimeError("Acao aprendida desktop_browser nao possui passos executaveis.")
    result = await executar_acao_rapida(
        action.key,
        steps,
        variables,
        action_config=action_config,
        run_id=run_id,
        cancellation_probe=_runtime_cancellation_probe(run_id, batch_id),
        progress_callback=progress_callback,
        timeline_callback=timeline_callback,
    )
    result["runner"] = "desktop_browser_replay"
    result["browser_mode"] = "desktop_browser"
    result["whether_desktop_browser_used"] = True
    return result


def _host_from_url(url: Any) -> str:
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _last_error_trace(step_trace: Any) -> dict[str, Any]:
    if not isinstance(step_trace, list):
        return {}
    for item in reversed(step_trace):
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "error":
            return item
    for item in reversed(step_trace):
        if isinstance(item, dict):
            return item
    return {}


def _last_successful_step_index(step_trace: Any) -> int | str:
    if not isinstance(step_trace, list):
        return ""
    successful = [
        item.get("step_index")
        for item in step_trace
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "success"
    ]
    return successful[-1] if successful else ""


def _diagnostic_step_source(diagnostics: dict[str, Any]) -> dict[str, Any]:
    trace_item = _last_error_trace(diagnostics.get("step_trace"))
    selector_items = diagnostics.get("selector_diagnostics")
    selector_item = selector_items[0] if isinstance(selector_items, list) and selector_items else {}
    step_items = diagnostics.get("step_diagnostics")
    step_item = step_items[-1] if isinstance(step_items, list) and step_items else {}
    return _first_dict(trace_item, selector_item, step_item, diagnostics)


def _build_error_payload(
    action: ActionDetail,
    request: ActionRunRequest,
    run: RunRecord,
    exc: Exception,
    diagnostics: dict[str, Any] | None,
    *,
    runner: str,
    browser_mode: str,
    whether_desktop_browser_used: bool,
) -> dict[str, Any]:
    raw_diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    step_source = _diagnostic_step_source(raw_diagnostics)
    current_url = str(
        raw_diagnostics.get("current_url")
        or step_source.get("current_url")
        or step_source.get("next_step_url_before")
        or ""
    )
    current_host = str(
        raw_diagnostics.get("current_host")
        or step_source.get("current_host")
        or step_source.get("current_url_host")
        or _host_from_url(current_url)
        or ""
    )
    page_title = str(
        raw_diagnostics.get("page_title")
        or raw_diagnostics.get("last_page_title")
        or step_source.get("page_title")
        or step_source.get("current_title")
        or ""
    )
    safe_error = _safe_error_message(exc)
    reason = str(raw_diagnostics.get("reason") or step_source.get("reason") or safe_error)
    payload: dict[str, Any] = {
        "run_id": run.id,
        "action_id": action.id,
        "action_key": action.key,
        "step_index": step_source.get("step_index", raw_diagnostics.get("next_step_index", "")),
        "step_type": step_source.get("step_type", step_source.get("action_type", raw_diagnostics.get("next_step_type", ""))),
        "step_selector": step_source.get("selector", step_source.get("step_selector", raw_diagnostics.get("next_step_selector", ""))),
        "step_value_template": step_source.get("value_template", step_source.get("step_value_template", step_source.get("valor", ""))),
        "step_variable_key": step_source.get("variable_key", step_source.get("step_variable_key", step_source.get("variavel", ""))),
        "current_url": current_url,
        "current_host": current_host,
        "page_title": page_title,
        "last_page_title": page_title,
        "screenshot_path": str(raw_diagnostics.get("screenshot_path") or step_source.get("screenshot_path") or ""),
        "reason": reason,
        "exception_type": type(exc).__name__,
        "exception_message": safe_error,
        "browser_mode": browser_mode,
        "runner": runner,
        "whether_desktop_browser_used": whether_desktop_browser_used,
        "last_successful_step_index": raw_diagnostics.get(
            "last_successful_step_index",
            _last_successful_step_index(raw_diagnostics.get("step_trace")),
        ),
        "next_step_expected_selector": raw_diagnostics.get("next_step_expected_selector", ""),
        "next_step_expected_text": raw_diagnostics.get("next_step_expected_text", ""),
        "input_variables": mask_variables(request.variables),
        "diagnostics": _json_safe(raw_diagnostics),
        "retryable": bool(raw_diagnostics.get("retryable", False)),
    }
    for key in (
        "operator_action_required",
        "session_state",
        "recovery_attempts",
        "recovery_steps",
        "recovery_attempted",
        "checkpoint_diagnostics",
        "next_step_index",
        "next_step_type",
        "next_step_selector",
        "next_step_url_before",
        "next_step_host_before",
        "next_step_expected_url_or_host",
        "whether_next_step_was_microsoft_click",
        "learned_microsoft_step_compatible",
        "next_step_selector_count",
        "next_step_selector_visible",
        "next_step_text_count",
        "next_step_text_visible",
        "matched_by",
        "variables_used",
        "downloaded_files",
        "dados_extraidos",
        "evidence",
        "step_trace",
        "step_diagnostics",
        "selector_diagnostics",
    ):
        value = raw_diagnostics.get(key)
        if value is not None and value != [] and value != {}:
            payload[key] = _json_safe(value)
    if "selector_diagnostics" not in payload:
        payload["selector_diagnostics"] = [_json_safe(step_source or {"reason": reason, "current_url": current_url, "current_host": current_host})]
    return payload


def start_action_run(
    action: ActionDetail,
    request: ActionRunRequest,
    *,
    run_type: str = "action_run",
) -> RunRecord:
    created_at = utc_now_iso()
    run = RunRecord(
        id=str(uuid4()),
        action_id=action.id,
        action_key=action.key,
        action_version_id=None,
        status="pending",
        mode=request.mode,
        run_type=str(run_type or "action_run"),
        run_origin=request.run_origin,
        requested_by=request.requested_by.strip() or "api",
        session_id=request.session_id,
        client_id=str(request.variables.get("client_id") or "") or None,
        batch_id=request.batch_id,
        access_profile_id=None,
        external_system_id=None,
        run_start_strategy=None,
        created_at=created_at,
        variables=mask_variables(request.variables),
    )
    with SessionLocal() as session:
        db_action = session.get(DbAction, action.id)
        version = session.get(ActionVersion, db_action.published_version_id) if db_action and db_action.published_version_id else None
        run.action_version_id = version.id if version else None
        client_id = str(request.variables.get("client_id") or "").strip()
        client = session.get(Client, client_id) if client_id else None
        profile_id = str(
            (version.required_access_profile_id if version else None)
            or (db_action.required_access_profile_id if not version and db_action else None)
            or ""
        ).strip() or None
        if client and client.list_id:
            client_list = session.get(ClientList, client.list_id)
            if client_list:
                if profile_id and profile_id != client_list.access_profile_id:
                    raise RuntimeError("A Action e a Lista usam perfis de acesso diferentes.")
        profile = session.get(ExternalAccessProfile, profile_id) if profile_id else None
        if version and version.run_start_strategy == "external_entry_each_run" and not version.required_access_profile_id:
            raise RuntimeError("REQUIRED_ACCESS_PROFILE_NOT_ASSIGNED: a versão publicada não possui perfil vinculado.")
        if version and version.required_access_profile_id and (profile is None or not profile.active):
            raise RuntimeError("REQUIRED_ACCESS_PROFILE_NOT_ASSIGNED: a Action precisa de uma reassociação explícita de perfil.")
        external_system = session.get(ExternalSystem, profile.external_system_id) if profile else None
        run.access_profile_id = profile.id if profile else None
        run.external_system_id = external_system.id if external_system else None
        run.run_start_strategy = version.run_start_strategy if version else None
    append_run(run)

    RunTimeline(
        run_id=run.id,
        context={
            "action_id": run.action_id,
            "action_version_id": run.action_version_id,
            "client_id": run.client_id,
            "access_profile_id": run.access_profile_id,
            "external_system_id": run.external_system_id,
            "run_start_strategy": run.run_start_strategy,
        },
    ).emit("run", "RUN_CREATED", "success")

    run.status = "running"
    run.started_at = utc_now_iso()
    update_run(run)
    return run


def _log_unhandled_run_task(task: asyncio.Task[Any], run_id: str) -> None:
    try:
        exception = task.exception()
    except asyncio.CancelledError:
        logger.warning("Run %s task cancelada antes de atingir estado terminal", run_id)
        return
    if exception is None:
        return
    logger.error(
        "Run %s task terminou com excecao nao tratada",
        run_id,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    try:
        persist_terminal_run_fallback(
            run_id,
            code="UNHANDLED_RUN_EXCEPTION",
            message="A tarefa de execução terminou com uma exceção não tratada.",
        )
    except Exception:
        logger.exception("Falha no fallback terminal do run %s", run_id)


def schedule_finish_action_run(
    action: ActionDetail,
    request: ActionRunRequest,
    run: RunRecord,
) -> asyncio.Task[Any]:
    task = asyncio.create_task(finish_action_run(action, request, run))
    task.add_done_callback(lambda completed: _log_unhandled_run_task(completed, run.id))
    return task


async def finish_action_run(action: ActionDetail, request: ActionRunRequest, run: RunRecord) -> RunRecord:
    runner_used = "local_fixture" if _is_local_fixture(action) else "action_runner"
    browser_mode_used = str(action.browser_mode or "desktop_browser").strip() or "desktop_browser"
    whether_desktop_browser_used = browser_mode_used == "desktop_browser"
    timeline = RunTimeline(
        run_id=run.id,
        context={
            "action_id": run.action_id,
            "action_version_id": run.action_version_id,
            "client_id": run.client_id,
            "access_profile_id": run.access_profile_id,
            "external_system_id": run.external_system_id,
            "run_start_strategy": run.run_start_strategy,
        },
    )
    timeline.emit("run", "RUN_STARTED", "success")
    terminal_exception: Exception | None = None
    try:
        if _is_local_fixture(action):
            run.status = "success"
            run.result_payload = _run_local_fixture(action, request.variables)
        elif action.steps_count <= 0:
            raise RuntimeError("Acao aprendida nao possui passos para execucao.")
        elif request.session_id:
            runner_used = "demo_session_replay"
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
            if run.result_payload is not None:
                run.result_payload.setdefault("input_variables", mask_variables(request.variables))
                run.result_payload.setdefault("run_id", run.id)
                run.result_payload.setdefault("action_id", action.id)
                run.result_payload.setdefault("action_key", action.key)
                run.result_payload.setdefault("browser_mode", browser_mode_used)
                run.result_payload.setdefault("runner", runner_used)
                run.result_payload.setdefault("whether_desktop_browser_used", browser_mode_used == "desktop_browser")
        elif _is_desktop_learned_action(action):
            runner_used = "desktop_browser_replay"
            browser_mode_used = "desktop_browser"
            whether_desktop_browser_used = True
            async def report_waiting(status: str) -> None:
                timeline.waiting(status)
                run.result_payload = {
                    "wait_status": "waiting_external_system",
                    "wait_target": status,
                    "run_id": run.id,
                }
                update_run(run)

            result = await _run_desktop_browser_replay(
                action,
                request.variables,
                run.id,
                batch_id=request.batch_id,
                progress_callback=report_waiting,
                timeline_callback=timeline.emit,
            )
            text = str(result.get("texto") or result.get("motivo") or "").strip()
            execution_status = str(result.get("status") or "").strip().lower()
            if execution_status in {"erro", "error"} or text.startswith("❌") or "Falha" in text or "falha" in text:
                execution_error = RuntimeError(
                    str(result.get("error_message") or result.get("motivo") or text or "Falha na execucao da acao.")
                )
                page_diagnostics = result.get("page_diagnostics")
                if isinstance(page_diagnostics, dict):
                    page_diagnostics.setdefault("runner", runner_used)
                    page_diagnostics.setdefault("browser_mode", browser_mode_used)
                    page_diagnostics.setdefault("whether_desktop_browser_used", True)
                    execution_error.diagnostics = page_diagnostics  # type: ignore[attr-defined]
                elif isinstance(result, dict):
                    execution_error.diagnostics = result  # type: ignore[attr-defined]
                raise execution_error

            _validate_desktop_result(action, result)
            run.status = "success"
            run.result_payload = _safe_result_payload(result)
            if run.result_payload is not None:
                run.result_payload.setdefault("input_variables", mask_variables(request.variables))
                run.result_payload.setdefault("run_id", run.id)
                run.result_payload.setdefault("action_id", action.id)
                run.result_payload.setdefault("action_key", action.key)
                run.result_payload.setdefault("browser_mode", browser_mode_used)
                run.result_payload.setdefault("runner", runner_used)
                run.result_payload.setdefault("whether_desktop_browser_used", True)
        else:
            raise RuntimeError("Acao antiga sem replay desktop_browser nao e suportada nesta arquitetura.")
    except Exception as exc:
        terminal_exception = exc
        safe_error = _safe_error_message(exc)
        logger.info("Run %s finalizada com erro do tipo %s", run.id, type(exc).__name__)
        run.status = "cancelled" if isinstance(exc, RuntimeWaitCancelled) else "error"
        run.error_message = safe_error
        diagnostics = getattr(exc, "diagnostics", None)
        if isinstance(diagnostics, dict):
            run.result_payload = _build_error_payload(
                action,
                request,
                run,
                exc,
                diagnostics,
                runner=runner_used,
                browser_mode=browser_mode_used,
                whether_desktop_browser_used=whether_desktop_browser_used,
            )
        else:
            run.result_payload = _build_error_payload(
                action,
                request,
                run,
                exc,
                {},
                runner=runner_used,
                browser_mode=browser_mode_used,
                whether_desktop_browser_used=whether_desktop_browser_used,
            )
    finally:
        try:
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
            timeline.emit(
                "run",
                "RUN_SUCCEEDED" if run.status == "success" else ("RUN_CANCELLED" if run.status == "cancelled" else "RUN_FAILED"),
                run.status,
                error_code=(getattr(terminal_exception, "code", None) if terminal_exception else None)
                or (type(terminal_exception).__name__ if terminal_exception else None),
                error_stage=(getattr(terminal_exception, "diagnostics", {}) or {}).get("error_stage")
                or (getattr(terminal_exception, "diagnostics", {}) or {}).get("stage")
                or ("runtime" if run.status in {"error", "cancelled"} else None),
                exception_class=type(terminal_exception).__name__ if terminal_exception else None,
            )
        except Exception as persistence_error:
            logger.exception("Run %s falhou no fechamento/persistencia", run.id)
            run.status = "error"
            run.error_message = "Falha interna ao finalizar a execução."
            if not isinstance(run.result_payload, dict):
                run.result_payload = {}
            run.result_payload["finalization_error"] = {
                "stage": "run_finalization",
                "exception_type": type(persistence_error).__name__,
                "exception_message": str(persistence_error)[:500],
            }
            run.finished_at = utc_now_iso()
            try:
                persist_terminal_run_fallback(
                    run.id,
                    code="UNHANDLED_RUN_EXCEPTION",
                    message="Falha ao persistir o estado terminal da execução.",
                )
            except Exception:
                logger.exception("Fallback terminal indisponivel para o run %s", run.id)
            try:
                update_run(run)
            except Exception:
                logger.exception("Persistencia secundaria indisponivel para o run %s", run.id)

    return run


async def run_action_sync(action: ActionDetail, request: ActionRunRequest) -> RunRecord:
    run = start_action_run(action, request)
    run = await finish_action_run(action, request, run)
    if run.status == "success" and isinstance(run.result_payload, dict):
        from backend.services.system_spreadsheets import apply_action_outputs_to_system_spreadsheet

        apply_action_outputs_to_system_spreadsheet(
            run_id=run.id,
            action_id=action.id,
            client_id=str(request.variables.get("client_id") or "") or None,
            variables=request.variables,
            result_payload=run.result_payload,
            outputs=[dict(item) for item in (action.outputs or []) if isinstance(item, dict)],
            batch_id=request.batch_id,
        )
        RunTimeline(run_id=run.id).emit("output", "OUTPUT_PERSISTED", "success")
    return run
