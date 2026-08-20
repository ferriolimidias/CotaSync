from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.api.demo import GuidedLearningRequest, OperatorInsertActiveRequest, OperatorPressRequest, SaveDemoActionRequest
from backend.api.desktop_browser import _public_view_url
from backend.db import Action as DbAction, ActionVersion, Batch as DbBatch, BatchItem, Run as DbRun, SessionLocal
from backend.services.actions_repository import ActionsRepositoryError, find_action, load_actions_catalog
from backend.services.auth import AuthUser, require_admin, require_user
from backend.services.batch_runner import (
    BatchIdempotencyConflict,
    BatchRunnerError,
    batch_results_csv,
    cancel_batch,
    create_batch,
    list_batches,
    load_batch,
)
from backend.services.browser_providers import configured_browser_mode, desktop_browser_health
from backend.services.clients_repository import (
    ClientsRepositoryError,
    create_client,
    deactivate_client,
    get_client,
    list_clients,
    update_client,
)
from backend.services.demo_session import DemoSessionError, demo_session_manager
from backend.services.desktop_view_tokens import create_token
from backend.services.external_systems import ExternalSystemConfigError, load_current_external_system
from backend.services.runs_repository import RunsRepositoryError, get_run, list_runs
from backend.worker import latest_worker_status

router = APIRouter(prefix="/api/v1", tags=["api-v1"])


class Page(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class ClientPayload(BaseModel):
    name: str
    group: str = "Lista Principal"
    active: bool = True
    notes: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class BatchCreatePayload(BaseModel):
    action_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    client_group: str | None = None
    client_ids: list[str] = Field(default_factory=list)
    requested_by: str = "api-v1"
    delay_between_rows_seconds: float = 3


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    total = len(items)
    start = (page - 1) * page_size
    return {"page": page, "page_size": page_size, "total": total, "items": items[start : start + page_size]}


def _batch_summary(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": batch.get("batch_id"),
        "status": batch.get("status"),
        "action_id": batch.get("action_id"),
        "total_items": batch.get("total_items"),
        "processed_items": batch.get("processed_items"),
        "success_items": batch.get("success_items"),
        "error_items": batch.get("error_items"),
        "interrupted_items": batch.get("interrupted_items"),
        "cancelled_items": batch.get("cancelled_items"),
        "current_position": batch.get("current_position"),
        "current_client_id": batch.get("current_client_id"),
        "heartbeat_at": batch.get("heartbeat_at"),
        "created_at": batch.get("created_at"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
    }


@router.get("/dashboard", summary="Resumo operacional para dashboard")
async def dashboard(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    with SessionLocal() as session:
        active_clients_count = session.execute(text("select count(*) from clients where active = true")).scalar()
        runs_today = session.query(DbRun).filter(DbRun.created_at >= today_start).count()
        last_run = session.query(DbRun).order_by(DbRun.created_at.desc()).first()
        queued = session.query(DbBatch).filter(DbBatch.status == "queued").count()
        running = session.query(DbBatch).filter(DbBatch.status.in_(["running", "cancel_requested"])).count()
    try:
        catalog = load_actions_catalog()
        actions_ready = len(catalog.actions)
    except ActionsRepositoryError:
        actions_ready = 0
    worker = latest_worker_status()
    alerts = []
    if not worker.get("online"):
        alerts.append({"level": "warning", "code": "WORKER_OFFLINE", "message": "Worker offline."})
    return {
        "status": "ok",
        "dashboard": {
            "session_status": "authenticated",
            "clients_active": int(active_clients_count or 0),
            "actions_ready": actions_ready,
            "runs_today": runs_today,
            "last_run": {"id": last_run.id, "status": last_run.status, "created_at": last_run.created_at.isoformat()} if last_run else None,
            "worker_status": worker,
            "queue_status": {"queued": queued, "running": running},
            "alerts": alerts,
        },
    }


@router.get("/clients", summary="Lista clientes com paginação")
async def clients_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    group: str | None = None,
    include_inactive: bool = True,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        clients = list_clients(group=group, include_inactive=include_inactive)
    except ClientsRepositoryError as exc:
        raise _error(500, "CLIENTS_UNAVAILABLE", str(exc)) from exc
    return {"status": "ok", "clients": _paginate(clients, page, page_size)}


@router.post("/clients", summary="Cria cliente")
async def clients_create(payload: ClientPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        client = create_client(payload.model_dump())
    except ClientsRepositoryError as exc:
        raise _error(422, "CLIENT_INVALID", str(exc)) from exc
    return {"status": "ok", "client": client}


@router.get("/clients/{client_id}", summary="Obtém cliente")
async def clients_get(client_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    client = get_client(client_id)
    if client is None:
        raise _error(404, "CLIENT_NOT_FOUND", "Cliente nao encontrado.")
    return {"status": "ok", "client": client}


@router.patch("/clients/{client_id}", summary="Atualiza cliente")
async def clients_patch(client_id: str, payload: ClientPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        client = update_client(client_id, payload.model_dump())
    except ClientsRepositoryError as exc:
        raise _error(404, "CLIENT_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "client": client}


@router.delete("/clients/{client_id}", summary="Desativa cliente")
async def clients_deactivate(client_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        client = deactivate_client(client_id)
    except ClientsRepositoryError as exc:
        raise _error(404, "CLIENT_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "client": client}


@router.get("/actions", summary="Lista ações publicadas")
async def actions_list(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        actions = [action.model_dump() for action in load_actions_catalog().actions]
    except ActionsRepositoryError as exc:
        raise _error(500, "ACTIONS_UNAVAILABLE", str(exc)) from exc
    return {"status": "ok", "actions": _paginate(actions, page, page_size)}


@router.get("/actions/{action_id}", summary="Detalhe de ação")
async def actions_get(action_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    action = find_action(action_id)
    if action is None:
        raise _error(404, "ACTION_NOT_FOUND", "Acao nao encontrada.")
    runs = list_runs(action_id=action.id, limit=1)
    payload = action.model_dump()
    payload["published_version"] = {"id": None, "status": "published"}
    payload["last_run"] = runs[0].model_dump() if runs else None
    payload["needs_attention"] = bool(action.learning_warnings or action.legacy_unconfigured)
    return {"status": "ok", "action": payload}


@router.get("/actions/{action_id}/versions", summary="Versões de uma ação")
async def action_versions(action_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    with SessionLocal() as session:
        action = session.get(DbAction, action_id)
        if action is None:
            raise _error(404, "ACTION_NOT_FOUND", "Acao nao encontrada.")
        versions = (
            session.query(ActionVersion)
            .filter(ActionVersion.action_id == action_id)
            .order_by(ActionVersion.version_number.desc())
            .all()
        )
        items = [
            {
                "id": version.id,
                "version_number": version.version_number,
                "status": version.status,
                "published": version.id == action.published_version_id,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "published_at": version.published_at.isoformat() if version.published_at else None,
            }
            for version in versions
        ]
    return {"status": "ok", "versions": items}


@router.get("/learning/capabilities", summary="Capacidades de aprendizado")
async def learning_capabilities(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {
        "status": "ok",
        "capabilities": {
            "sessions": True,
            "recording": True,
            "operator_assistant": True,
            "canonical_variables": ["grupo", "cota", "versao"],
        },
    }


@router.post("/learning/sessions", summary="Cria sessão de aprendizado")
async def learning_create_session(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        session = await demo_session_manager.create()
    except DemoSessionError as exc:
        raise _error(503, "LEARNING_SESSION_UNAVAILABLE", str(exc)) from exc
    return {"status": "ok", "session": session}


@router.get("/learning/sessions/{session_id}", summary="Estado da sessão de aprendizado")
async def learning_get_session(session_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        session = await demo_session_manager.status(session_id)
    except DemoSessionError as exc:
        raise _error(404, "LEARNING_SESSION_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "session": session}


@router.post("/learning/sessions/{session_id}/recording/start", summary="Inicia gravação")
async def learning_start_recording(session_id: str, payload: GuidedLearningRequest | None = None, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        session = await demo_session_manager.start_recording(session_id, payload.model_dump() if payload is not None else {})
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_RECORDING_ERROR", str(exc)) from exc
    return {"status": "ok", "session": session}


@router.post("/learning/sessions/{session_id}/recording/stop", summary="Finaliza gravação")
async def learning_stop_recording(session_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await demo_session_manager.stop_recording(session_id)
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_RECORDING_ERROR", str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/learning/sessions/{session_id}/actions", summary="Publica ação aprendida")
async def learning_save_action(session_id: str, payload: SaveDemoActionRequest, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        action = await demo_session_manager.save_action(
            session_id,
            payload.name,
            payload.description,
            payload.variable_names,
            objective=payload.objective,
            input_description=payload.input_description,
            expected_result=payload.expected_result,
            success_criteria=payload.success_criteria,
            output_type=payload.output_type,
            user_result_summary_template=payload.user_result_summary_template,
            ai_result_summary_enabled=payload.ai_result_summary_enabled,
            ai_recovery_enabled=payload.ai_recovery_enabled,
            extraction_targets=payload.extraction_targets,
            extract_visible_text=payload.extract_visible_text,
            return_downloaded_file=payload.return_downloaded_file,
            requires_authenticated_session=payload.requires_authenticated_session,
            action_timeout_seconds=payload.action_timeout_seconds,
        )
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_SAVE_ERROR", str(exc)) from exc
    return {"status": "ok", "action": action}


@router.post("/learning/sessions/{session_id}/operator/insert-active", summary="Insere texto no campo ativo")
async def learning_insert_active(session_id: str, payload: OperatorInsertActiveRequest, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await demo_session_manager.operator_insert_active(session_id, payload.value, sensitive=payload.sensitive)
    except DemoSessionError as exc:
        raise _error(409, "OPERATOR_ACTION_ERROR", str(exc)) from exc
    if payload.sensitive and isinstance(result, dict):
        result.pop("value", None)
        result.pop("text", None)
    return {"status": "ok", "operator": result}


@router.post("/learning/sessions/{session_id}/operator/press", summary="Pressiona tecla permitida")
async def learning_press(session_id: str, payload: OperatorPressRequest, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    allowed = {"Tab", "Enter", "Escape", "Backspace", "Delete", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"}
    if payload.key not in allowed:
        raise _error(422, "OPERATOR_KEY_NOT_ALLOWED", "Tecla nao permitida.")
    try:
        result = await demo_session_manager.operator_press(session_id, payload.key)
    except DemoSessionError as exc:
        raise _error(409, "OPERATOR_ACTION_ERROR", str(exc)) from exc
    return {"status": "ok", "operator": result}


@router.post("/learning/sessions/{session_id}/operator/clear-active", summary="Limpa campo ativo")
async def learning_clear_active(session_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await demo_session_manager.operator_clear_active(session_id)
    except DemoSessionError as exc:
        raise _error(409, "OPERATOR_ACTION_ERROR", str(exc)) from exc
    return {"status": "ok", "operator": result}


@router.get("/browser/status", summary="Status do desktop browser")
async def browser_status(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {"status": "ok", "browser": {"browser_mode": configured_browser_mode(), "desktop_browser": await desktop_browser_health()}}


@router.post("/browser/view-token", summary="Cria token curto para noVNC")
async def browser_view_token(response: Response, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    created = create_token()
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "view_url": _public_view_url(created.token), "expires_at": created.expires_at.isoformat(), "ttl_seconds": created.ttl_seconds}


@router.post("/browser/ensure-ready", summary="Verifica prontidão do browser")
async def browser_ensure_ready(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    health = await desktop_browser_health()
    if not health.get("cdp_reachable"):
        raise _error(503, "BROWSER_UNAVAILABLE", "Desktop browser indisponivel.")
    return {"status": "ok", "browser": health}


@router.get("/external-session/status", summary="Status de sessão externa")
async def external_session_status(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        config = load_current_external_system()
    except ExternalSystemConfigError as exc:
        raise _error(500, "EXTERNAL_SESSION_UNAVAILABLE", str(exc)) from exc
    return {
        "status": "ok",
        "external_session": {
            "external_system_name": config.get("external_system_name", ""),
            "login_url_configured": bool(config.get("external_login_url")),
            "manual_login_required": True,
            "automation": "manual_operator",
        },
    }


@router.post("/external-session/open-login", summary="Retorna URL de login configurada")
async def external_session_open_login(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    config = load_current_external_system()
    login_url = str(config.get("external_login_url") or "")
    if not login_url:
        raise _error(422, "EXTERNAL_LOGIN_URL_MISSING", "URL de login externa nao configurada.")
    return {"status": "ok", "login_url": login_url, "manual_login_required": True}


@router.post("/external-session/validate", summary="Valida configuração de sessão externa")
async def external_session_validate(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    config = load_current_external_system()
    return {"status": "ok", "valid": bool(config.get("external_system_name")), "manual_login_required": True}


@router.post("/batches", summary="Cria batch para worker")
async def batches_create(
    request: Request,
    payload: BatchCreatePayload,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    del request
    try:
        batch = create_batch(
            action_id=payload.action_id,
            rows=payload.rows,
            client_group=payload.client_group,
            client_ids=payload.client_ids,
            requested_by=payload.requested_by,
            delay_between_rows_seconds=payload.delay_between_rows_seconds,
            idempotency_key=idempotency_key,
            idempotency_user_id=user.username,
        )
    except BatchIdempotencyConflict as exc:
        raise _error(409, "BATCH_IDEMPOTENCY_CONFLICT", str(exc)) from exc
    except BatchRunnerError as exc:
        raise _error(422, "BATCH_INVALID", str(exc)) from exc
    return {"status": "ok", "batch": batch}


@router.get("/batches", summary="Lista batches")
async def batches_list(page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=200), _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    batches = [_batch_summary(batch) for batch in list_batches(limit=200)]
    return {"status": "ok", "batches": _paginate(batches, page, page_size)}


@router.get("/batches/{batch_id}", summary="Detalhe/progresso de batch")
async def batches_get(batch_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    batch = load_batch(batch_id)
    if batch is None:
        raise _error(404, "BATCH_NOT_FOUND", "Batch nao encontrado.")
    return {"status": "ok", "batch": batch}


@router.post("/batches/{batch_id}/cancel", summary="Cancela batch após item atual")
async def batches_cancel(batch_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        batch = cancel_batch(batch_id)
    except BatchRunnerError as exc:
        raise _error(404, "BATCH_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "batch": batch}


@router.get("/batches/{batch_id}/results", summary="Resultados CSV do batch")
async def batches_results(batch_id: str, _user: AuthUser = Depends(require_user)) -> FastAPIResponse:
    batch = load_batch(batch_id)
    if batch is None:
        raise _error(404, "BATCH_NOT_FOUND", "Batch nao encontrado.")
    return FastAPIResponse(content=batch_results_csv(batch), media_type="text/csv; charset=utf-8")


@router.get("/worker/status", summary="Status do worker")
async def worker_status(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {"status": "ok", "worker": latest_worker_status()}


@router.get("/reports/runs", summary="Histórico paginado de runs")
async def reports_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    action_id: str | None = None,
    status: str | None = None,
    run_origin: str | None = None,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        runs = [run.model_dump() for run in list_runs(action_id=action_id, status=status, limit=500)]  # type: ignore[arg-type]
    except RunsRepositoryError as exc:
        raise _error(500, "RUNS_UNAVAILABLE", str(exc)) from exc
    if run_origin:
        runs = [run for run in runs if run.get("run_origin") == run_origin]
    return {"status": "ok", "runs": _paginate(runs, page, page_size)}


@router.get("/reports/batches", summary="Histórico paginado de batches")
async def reports_batches(page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200), status: str | None = None, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    batches = list_batches(limit=200)
    if status:
        batches = [batch for batch in batches if batch.get("status") == status]
    return {"status": "ok", "batches": _paginate([_batch_summary(batch) for batch in batches], page, page_size)}


@router.get("/diagnostics/system", summary="Diagnóstico técnico do sistema")
async def diagnostics_system(_admin: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    return {
        "status": "ok",
        "diagnostics": {
            "worker": latest_worker_status(),
            "browser_mode": configured_browser_mode(),
            "browser": await desktop_browser_health(),
        },
    }


@router.get("/diagnostics/runs/{run_id}", summary="Diagnóstico técnico de run")
async def diagnostics_run(run_id: str, _admin: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    run = get_run(run_id)
    if run is None:
        raise _error(404, "RUN_NOT_FOUND", "Run nao encontrada.")
    with SessionLocal() as session:
        row = session.get(DbRun, run_id)
        diagnostics = row.diagnostics if row is not None else {}
        step_trace = row.step_trace if row is not None else []
        error_data = row.error_data if row is not None else {}
    return {"status": "ok", "run": run.model_dump(), "diagnostics": diagnostics, "step_trace": step_trace, "error_data": error_data}
