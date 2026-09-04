from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.api.demo import GuidedLearningRequest, OperatorInsertActiveRequest, OperatorPressRequest, SaveDemoActionRequest
from backend.api.desktop_browser import _public_view_url
from backend.db import Action as DbAction, ActionVersion, Batch as DbBatch, BatchItem, Run as DbRun, SessionLocal
from backend.services.action_pages import is_reauthentication_url, url_host
from backend.services.actions_repository import (
    ActionDeletionError,
    ActionsRepositoryError,
    delete_or_archive_action,
    find_action,
    load_actions_catalog,
)
from backend.services.action_runner import missing_required_variables, run_action_sync, schedule_finish_action_run, start_action_run
from backend.services.auth import AuthUser, require_admin, require_user
from backend.services.batch_runner import (
    BatchIdempotencyConflict,
    BatchRunnerError,
    batch_results_csv,
    cancel_batch,
    create_batch,
    list_batches,
    load_batch,
    resume_batch,
)
from backend.services.browser_providers import browser_provider, configured_browser_mode, desktop_browser_health
from backend.services.clients_repository import (
    ClientsRepositoryError,
    CLIENT_TEMPLATE_COLUMNS,
    create_client,
    deactivate_client,
    get_client,
    get_client_display_fields,
    list_clients,
    parse_clients_csv,
    update_client,
)
from backend.services.demo_session import DemoSessionError, demo_session_manager
from backend.services.desktop_view_tokens import create_token, validate_token
from backend.services.external_systems import ExternalSystemConfigError, load_current_external_system, save_current_external_system
from backend.services.data_sources import DataSourceError, get_source, list_sources, upsert_source_schema
from backend.services.learning_ai import LearningAIObserver
from backend.services.ai_settings import public_settings, remove_key, save_settings
from backend.services.learning_trace import build_raw_learning_trace
from backend.services.system_spreadsheets import (
    SystemSpreadsheetError,
    connector_service_account_email,
    attach_excel,
    attach_google,
    export_excel,
    get_system_spreadsheet,
    get_system_spreadsheet_rows,
    import_excel,
    import_google,
    list_system_spreadsheets,
    reconcile_schema,
    sync_google,
    test_google_connection,
    update_system_spreadsheet_row,
)
from backend.services.runs_repository import RunsRepositoryError, get_run, list_runs
from backend.services.client_lists import ClientListError, create_client_list, list_client_lists
from backend.worker import latest_worker_status
from playwright.async_api import async_playwright

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
    list_id: str | None = None


class BatchCreatePayload(BaseModel):
    action_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    client_group: str | None = None
    client_ids: list[str] = Field(default_factory=list)
    requested_by: str = "api-v1"
    delay_between_rows_seconds: float = 3


class ActionRunPayload(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    mode: str = "async"
    requested_by: str = "api-v1"
    session_id: str | None = None
    run_origin: str = "operational"


class ExternalSystemConfigPayload(BaseModel):
    external_system_name: str = ""
    external_login_url: str = ""
    access_profile_email_or_identifier: str = ""
    expected_system_host: str = ""


class ExternalSessionLoginPayload(BaseModel):
    force: bool = False


class ClientsCsvPayload(BaseModel):
    filename: str = "clientes.csv"
    csv_text: str = Field(min_length=1)


class DataSourceSchemaPayload(BaseModel):
    name: str
    source_type: str
    headers: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)


class SystemSpreadsheetCreatePayload(BaseModel):
    name: str
    headers: list[str] = Field(default_factory=lambda: ["Nome", "Grupo", "Cota", "Versão"])
    identity_mapping: dict[str, Any] = Field(default_factory=dict)
    list_id: str | None = None


class GoogleSpreadsheetPayload(BaseModel):
    url_or_id: str
    name: str = "Planilha Google"
    tab: str = ""
    list_id: str | None = None


class ExcelSpreadsheetPayload(BaseModel):
    name: str
    filename: str = "clientes.xlsx"
    content_base64: str
    sheet_name: str | None = None
    header_row: int = Field(default=1, ge=1)
    identity_mapping: dict[str, Any] = Field(default_factory=dict)
    list_id: str | None = None


class SystemSpreadsheetRowPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class AISettingsPayload(BaseModel):
    enabled: bool = False
    provider: str = "openai_compatible"
    model: str = "gpt-4o-mini"
    base_url: str = ""
    api_key: str | None = None


MAX_CLIENTS_CSV_BYTES = 1_048_576
MAX_CLIENTS_CSV_ROWS = 1_000
CLIENTS_CSV_SUPPORTED_HEADERS = {
    "id",
    "name",
    "group",
    "active",
    "grupo",
    "cota",
    "grupo_2",
    "versao",
    "vers_o",
    "grupo_3",
    "notes",
}
CLIENTS_CSV_CONFLICT_GROUPS = {
    "cota": ("cota", "grupo_2"),
    "versao": ("versao", "vers_o", "grupo_3"),
}


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
        "action_key": batch.get("action_key"),
        "action_name": batch.get("action_name"),
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


def _csv_text_with_limits(payload: ClientsCsvPayload) -> str:
    filename = str(payload.filename or "")
    if filename and not filename.lower().endswith(".csv"):
        raise _error(422, "CLIENTS_CSV_INVALID", "Envie um arquivo CSV.")
    try:
        size = len(payload.csv_text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _error(422, "CLIENTS_CSV_ENCODING", "CSV deve estar em UTF-8.") from exc
    if size > MAX_CLIENTS_CSV_BYTES:
        raise _error(413, "CLIENTS_CSV_TOO_LARGE", "CSV deve ter no maximo 1 MB.")
    return payload.csv_text.lstrip("\ufeff")


def _raw_csv_rows(csv_text: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        headers = [str(header or "").lstrip("\ufeff").strip() for header in (reader.fieldnames or [])]
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            row = {
                str(key or "").lstrip("\ufeff").strip(): "" if value is None else str(value).strip()
                for key, value in (raw_row or {}).items()
                if key is not None and str(key).strip()
            }
            if any(value.strip() for value in row.values()):
                rows.append(row)
            if len(rows) > MAX_CLIENTS_CSV_ROWS:
                raise _error(413, "CLIENTS_CSV_TOO_MANY_ROWS", "CSV deve ter no maximo 1000 linhas.")
    except csv.Error as exc:
        raise _error(422, "CLIENTS_CSV_INVALID", "CSV invalido.") from exc
    if not headers:
        raise _error(422, "CLIENTS_CSV_HEADERS_MISSING", "CSV precisa de cabecalho.")
    unknown = sorted({header for header in headers if header not in CLIENTS_CSV_SUPPORTED_HEADERS})
    if unknown:
        raise _error(422, "CLIENTS_CSV_UNSUPPORTED_HEADERS", f"Cabecalhos nao suportados: {', '.join(unknown)}.")
    return headers, rows


def _conflicts_for_raw_row(row_number: int, raw_row: dict[str, str]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for canonical, aliases in CLIENTS_CSV_CONFLICT_GROUPS.items():
        values = {alias: str(raw_row.get(alias) or "").strip() for alias in aliases}
        filled = {key: value for key, value in values.items() if value}
        if len(set(filled.values())) > 1:
            conflicts.append(
                {
                    "row_number": row_number,
                    "field": canonical,
                    "message": f"Valores divergentes para {canonical}.",
                    "values": filled,
                }
            )
    return conflicts


def _clients_import_preview(csv_text: str) -> dict[str, Any]:
    headers, raw_rows = _raw_csv_rows(csv_text)
    parsed = parse_clients_csv(csv_text)
    existing = list_clients(include_inactive=True)
    existing_ids = {str(client.get("id") or "") for client in existing}
    existing_name_group = {
        (str(client.get("name") or "").casefold(), str(client.get("group") or "").casefold())
        for client in existing
    }
    invalid: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    preview_rows: list[dict[str, Any]] = []
    new_clients = 0
    updates = 0
    for index, raw in enumerate(raw_rows, start=2):
        row_conflicts = _conflicts_for_raw_row(index, raw)
        conflicts.extend(row_conflicts)
        parsed_row = parsed[index - 2] if index - 2 < len(parsed) else {}
        row_errors = []
        if not str(parsed_row.get("name") or "").strip():
            row_errors.append("Nome do cliente e obrigatorio.")
        if row_conflicts:
            row_errors.append("Ha campos equivalentes com valores diferentes.")
        if row_errors:
            invalid.append({"row_number": index, "errors": row_errors})
        raw_id = str(parsed_row.get("id") or "").strip()
        name_group = (
            str(parsed_row.get("name") or "").casefold(),
            str(parsed_row.get("group") or "").casefold(),
        )
        operation = "update" if (raw_id and raw_id in existing_ids) or name_group in existing_name_group else "create"
        if operation == "update":
            updates += 1
        else:
            new_clients += 1
        variables = parsed_row.get("variables", {}) if isinstance(parsed_row, dict) else {}
        display = get_client_display_fields({"variables": variables})
        if len(preview_rows) < 50:
            preview_rows.append(
                {
                    "row_number": index,
                    "operation": operation,
                    "valid": not row_errors,
                    "name": parsed_row.get("name", ""),
                    "group": parsed_row.get("group", ""),
                    "active": parsed_row.get("active", True),
                    "display_variables": display,
                    "notes": parsed_row.get("notes", ""),
                    "errors": row_errors,
                }
            )
    if not raw_rows:
        warnings.append({"code": "EMPTY_CSV", "message": "CSV sem linhas de clientes."})
    if len(raw_rows) > len(preview_rows):
        warnings.append({"code": "PREVIEW_TRUNCATED", "message": "Preview mostra as primeiras 50 linhas."})
    valid_rows = len(raw_rows) - len(invalid)
    return {
        "filename": "",
        "limits": {
            "max_bytes": MAX_CLIENTS_CSV_BYTES,
            "max_rows": MAX_CLIENTS_CSV_ROWS,
            "encoding": "utf-8",
            "supported_headers": sorted(CLIENTS_CSV_SUPPORTED_HEADERS),
        },
        "headers": headers,
        "total_rows": len(raw_rows),
        "valid_rows": valid_rows,
        "invalid_rows": len(invalid),
        "new_clients": new_clients,
        "updates": updates,
        "conflicts": conflicts,
        "warnings": warnings,
        "rows": preview_rows,
        "can_import": valid_rows > 0 and not invalid and not conflicts,
    }


def _clients_export_csv(clients: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CLIENT_TEMPLATE_COLUMNS)
    writer.writeheader()
    for client in clients:
        display = client.get("display_variables") or get_client_display_fields(client)
        writer.writerow(
            {
                "id": client.get("id", ""),
                "name": client.get("name", ""),
                "group": client.get("group", ""),
                "active": "true" if client.get("active", True) else "false",
                "grupo": display.get("grupo", ""),
                "cota": display.get("cota", ""),
                "versao": display.get("versao", ""),
                "notes": client.get("notes", ""),
            }
        )
    return output.getvalue()


def _run_matches_filters(run: dict[str, Any], *, client: str | None, date_from: str | None, date_to: str | None) -> bool:
    if client:
        wanted = client.casefold()
        haystack = " ".join(
            [
                str(run.get("client_id") or ""),
                str((run.get("variables") or {}).get("client_id") or ""),
                str((run.get("variables") or {}).get("name") or ""),
                str((run.get("variables") or {}).get("cliente") or ""),
            ]
        ).casefold()
        if wanted not in haystack:
            return False
    created = str(run.get("created_at") or "")
    if date_from and created[:10] < date_from:
        return False
    if date_to and created[:10] > date_to:
        return False
    return True


def _runs_csv(runs: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    columns = ["id", "created_at", "action_id", "action_key", "status", "run_origin", "requested_by", "result", "error"]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for run in runs:
        writer.writerow(
            {
                "id": run.get("id", ""),
                "created_at": run.get("created_at", ""),
                "action_id": run.get("action_id", ""),
                "action_key": run.get("action_key", ""),
                "status": run.get("status", ""),
                "run_origin": run.get("run_origin", ""),
                "requested_by": run.get("requested_by", ""),
                "result": run.get("operational_summary") or run.get("result_summary") or "",
                "error": run.get("error_message") or "",
            }
        )
    return output.getvalue()


def _external_session_payload(config: dict[str, Any]) -> dict[str, Any]:
    system_name = str(config.get("external_system_name") or "").strip()
    login_url = str(config.get("external_login_url") or "").strip()
    validation_mode = str(config.get("validation") or "").strip() or "manual_confirmation"
    configured = bool(system_name and login_url)
    return {
        "external_system_name": system_name,
        "external_system_configured": configured,
        "login_url_configured": bool(login_url),
        "login_configured": bool(login_url),
        "manual_login_required": True,
        "login_mode": "manual",
        "automation": "manual_operator",
        "validation_mode": validation_mode,
        "session_status": "unknown" if configured else "not_configured",
        "expected_system_host_configured": bool(str(config.get("expected_system_host") or "").strip()),
        "updated_at": config.get("updated_at"),
    }


def _external_system_config_payload(config: dict[str, Any]) -> dict[str, Any]:
    system_name = str(config.get("external_system_name") or "").strip()
    login_url = str(config.get("external_login_url") or "")
    configured = bool(system_name and login_url.strip())
    return {
        "external_system_name": system_name,
        "external_login_url": login_url,
        "access_profile_email_or_identifier": str(
            config.get("access_profile_email_or_identifier")
            or config.get("microsoft_saved_account_identifier")
            or "",
        ).strip()
        if configured
        else "",
        "expected_system_host": str(config.get("expected_system_host") or "").strip() if configured else "",
        "updated_at": config.get("updated_at"),
    }


async def _navigate_desktop_browser(url: str) -> None:
    playwright = await async_playwright().start()
    try:
        connection = await browser_provider("desktop_browser").connect(playwright, "external-login")
        await connection.page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    finally:
        await playwright.stop()


async def _current_desktop_url() -> str:
    playwright = await async_playwright().start()
    try:
        connection = await browser_provider("desktop_browser").connect(playwright, "external-status")
        return str(connection.page.url or "")
    finally:
        await playwright.stop()


def _redirect_uri_host(login_url: str) -> str:
    try:
        parsed = urlsplit(str(login_url or "").strip())
        redirect_uri = parse_qs(parsed.query).get("redirect_uri", [""])[0]
        return url_host(redirect_uri)
    except (ValueError, IndexError):
        return ""


def _expected_external_hosts(config: dict[str, Any]) -> set[str]:
    expected_host = str(config.get("expected_system_host") or "").strip().lower().rstrip(".")
    login_url = str(config.get("external_login_url") or "")
    hosts = {
        expected_host,
        _redirect_uri_host(login_url),
    }
    return {host for host in hosts if host}


async def _external_session_status_from_browser(config: dict[str, Any]) -> str:
    external_session = _external_session_payload(config)
    if not external_session["external_system_configured"]:
        return "not_configured"
    health = await desktop_browser_health()
    if not health.get("cdp_reachable"):
        return "browser_offline"
    try:
        current_url = await _current_desktop_url()
    except Exception:
        return "unknown"
    current_host = url_host(current_url)
    expected_hosts = _expected_external_hosts(config)
    if current_host and current_host in expected_hosts:
        return "authenticated"
    if is_reauthentication_url(current_url, expected_hosts):
        return "unauthenticated"
    return "unknown"


def _action_executable(action: Any) -> bool:
    return bool(
        getattr(action, "published_version", None) is not None
        or (
            getattr(action, "steps_count", 0) > 0
            and getattr(action, "has_url", False)
            and not getattr(action, "legacy_unconfigured", False)
        )
    )


@router.get("/dashboard", summary="Resumo operacional para dashboard")
async def dashboard(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    with SessionLocal() as session:
        active_clients_count = session.execute(text("select count(*) from clients where active = true")).scalar()
        runs_today = session.query(DbRun).filter(DbRun.created_at >= today_start).count()
        last_run = session.query(DbRun).order_by(DbRun.created_at.desc()).first()
        queued = session.query(DbBatch).filter(DbBatch.status == "queued").count()
        running = session.query(DbBatch).filter(DbBatch.status.in_(["running", "cancel_requested"])).count()
    alerts = []
    try:
        external_session = _external_session_payload(load_current_external_system())
    except ExternalSystemConfigError:
        external_session = _external_session_payload({})
        external_session["session_status"] = "unknown"
        alerts.append(
            {
                "level": "warning",
                "code": "EXTERNAL_SESSION_UNAVAILABLE",
                "message": "Configuracao externa indisponivel.",
            }
        )
    try:
        catalog = load_actions_catalog()
        actions_ready = len([action for action in catalog.actions if _action_executable(action)])
    except ActionsRepositoryError:
        actions_ready = 0
    worker = latest_worker_status()
    if not worker.get("online"):
        alerts.append({"level": "warning", "code": "WORKER_OFFLINE", "message": "Worker offline."})
    return {
        "status": "ok",
        "dashboard": {
            "session_status": external_session["session_status"],
            "external_session": external_session,
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
    list_id: str | None = None,
    search: str | None = None,
    include_inactive: bool = True,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        clients = list_clients(group=group, list_id=list_id, include_inactive=include_inactive, search=search)
    except ClientsRepositoryError as exc:
        raise _error(500, "CLIENTS_UNAVAILABLE", str(exc)) from exc
    return {"status": "ok", "clients": _paginate(clients, page, page_size)}


@router.post("/clients/import/preview", summary="Preview validado de CSV de clientes")
async def clients_import_preview(payload: ClientsCsvPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    csv_text = _csv_text_with_limits(payload)
    preview = _clients_import_preview(csv_text)
    preview["filename"] = payload.filename
    return {"status": "ok", "preview": preview}


@router.post("/clients/import", summary="Importa CSV de clientes apos preview")
async def clients_import(payload: ClientsCsvPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    csv_text = _csv_text_with_limits(payload)
    preview = _clients_import_preview(csv_text)
    if not preview["can_import"]:
        raise _error(422, "CLIENTS_CSV_HAS_ERRORS", "Corrija os conflitos e linhas invalidas antes de importar.")
    try:
        parsed = parse_clients_csv(csv_text)
        created = 0
        updated = 0
        clients = []
        existing = list_clients(include_inactive=True)
        by_id = {str(client.get("id") or ""): client for client in existing}
        by_name_group = {
            (str(client.get("name") or "").casefold(), str(client.get("group") or "").casefold()): client
            for client in existing
        }
        for raw in parsed:
            raw_id = str(raw.get("id") or "").strip()
            existing_client = by_id.get(raw_id) if raw_id else None
            existing_client = existing_client or by_name_group.get(
                (str(raw.get("name") or "").casefold(), str(raw.get("group") or "").casefold())
            )
            if existing_client:
                clients.append(update_client(str(existing_client["id"]), raw))
                updated += 1
            else:
                clients.append(create_client(raw))
                created += 1
    except ClientsRepositoryError as exc:
        raise _error(422, "CLIENTS_CSV_IMPORT_FAILED", str(exc)) from exc
    headers = next(csv.reader(io.StringIO(csv_text)), [])
    try:
        source = upsert_source_schema(name=payload.filename or "Clientes", source_type="excel", headers=headers)
    except DataSourceError:
        source = None
    return {"status": "ok", "import_result": {"created": created, "updated": updated, "count": len(clients), "clients": clients, "data_source": source}}


@router.get("/data-sources", summary="Lista fontes de dados configuradas")
async def data_sources_list(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {"status": "ok", "data_sources": list_sources()}


@router.get("/system-spreadsheets", summary="Lista as planilhas canônicas do sistema")
async def system_spreadsheets_list(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {"status": "ok", "system_spreadsheets": list_system_spreadsheets()}


@router.get("/client-lists", summary="Lista as listas operacionais de clientes")
async def client_lists_list(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {"status": "ok", "client_lists": list_client_lists()}


@router.post("/client-lists", summary="Cria uma lista operacional de clientes")
async def client_list_create(payload: dict[str, Any], _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"status": "ok", "client_list": create_client_list(str(payload.get("name") or ""))}
    except ClientListError as exc:
        raise _error(422, "CLIENT_LIST_INVALID", str(exc)) from exc


@router.post("/system-spreadsheets", summary="Cria uma planilha no CotaSync")
async def system_spreadsheet_create(payload: SystemSpreadsheetCreatePayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    from backend.services.system_spreadsheets import create_system_spreadsheet
    try:
        sheet = create_system_spreadsheet(payload.name, payload.headers, identity_mapping=payload.identity_mapping, list_id=payload.list_id)
    except SystemSpreadsheetError as exc:
        raise _error(422, "SYSTEM_SPREADSHEET_INVALID", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.get("/system-spreadsheets/{spreadsheet_id}", summary="Abre uma planilha do sistema")
async def system_spreadsheet_get(spreadsheet_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        sheet = get_system_spreadsheet(spreadsheet_id)
    except SystemSpreadsheetError as exc:
        raise _error(404, "SYSTEM_SPREADSHEET_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.get("/system-spreadsheets/{spreadsheet_id}/rows", summary="Lista as linhas internas da planilha")
async def system_spreadsheet_rows(spreadsheet_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"status": "ok", **get_system_spreadsheet_rows(spreadsheet_id)}
    except SystemSpreadsheetError as exc:
        raise _error(404, "SYSTEM_SPREADSHEET_NOT_FOUND", str(exc)) from exc


@router.patch("/system-spreadsheets/{spreadsheet_id}/rows/{client_id}", summary="Edita campos não identitários de uma linha")
async def system_spreadsheet_row_update(spreadsheet_id: str, client_id: str, payload: SystemSpreadsheetRowPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"status": "ok", **update_system_spreadsheet_row(spreadsheet_id, client_id, payload.values)}
    except SystemSpreadsheetError as exc:
        raise _error(422, "SYSTEM_SPREADSHEET_ROW_UPDATE_FAILED", str(exc)) from exc


@router.post("/system-spreadsheets/{spreadsheet_id}/schema", summary="Reconcilia campos da planilha do sistema")
async def system_spreadsheet_schema(spreadsheet_id: str, payload: SystemSpreadsheetCreatePayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        sheet = reconcile_schema(spreadsheet_id, payload.headers)
    except SystemSpreadsheetError as exc:
        raise _error(422, "SYSTEM_SPREADSHEET_SCHEMA_INVALID", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.post("/system-spreadsheets/import-excel", summary="Importa um workbook Excel para a planilha do sistema")
async def system_spreadsheet_import_excel(payload: ExcelSpreadsheetPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    import base64
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
        sheet = import_excel(name=payload.name, content=content, filename=payload.filename, sheet_name=payload.sheet_name, header_row=payload.header_row, identity_mapping=payload.identity_mapping, list_id=payload.list_id)
    except (ValueError, SystemSpreadsheetError) as exc:
        raise _error(422, "EXCEL_IMPORT_FAILED", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.post("/system-spreadsheets/{spreadsheet_id}/connectors/excel", summary="Anexa Excel a uma planilha existente")
async def system_spreadsheet_attach_excel(spreadsheet_id: str, payload: ExcelSpreadsheetPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    import base64
    try:
        sheet = attach_excel(sheet_id=spreadsheet_id, content=base64.b64decode(payload.content_base64, validate=True), filename=payload.filename, sheet_name=payload.sheet_name, header_row=payload.header_row)
    except (ValueError, SystemSpreadsheetError) as exc:
        raise _error(422, "EXCEL_CONNECTOR_FAILED", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.get("/system-spreadsheets/{spreadsheet_id}/export.xlsx", summary="Baixa a planilha do sistema em Excel")
async def system_spreadsheet_export_excel(spreadsheet_id: str, _user: AuthUser = Depends(require_user)) -> FastAPIResponse:
    try:
        content = export_excel(spreadsheet_id)
    except SystemSpreadsheetError as exc:
        raise _error(404, "EXCEL_EXPORT_FAILED", str(exc)) from exc
    return FastAPIResponse(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="cotasync.xlsx"'})


@router.post("/system-spreadsheets/google/test", summary="Testa acesso Google Sheets")
async def system_spreadsheet_google_test(payload: GoogleSpreadsheetPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"status": "ok", "google": test_google_connection(payload.url_or_id)}
    except SystemSpreadsheetError as exc:
        raise _error(422, "GOOGLE_SHEETS_CONNECTION_FAILED", str(exc)) from exc


@router.post("/system-spreadsheets/import-google", summary="Importa uma aba Google para a planilha do sistema")
async def system_spreadsheet_import_google(payload: GoogleSpreadsheetPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        sheet = import_google(name=payload.name, url_or_id=payload.url_or_id, tab=payload.tab, list_id=payload.list_id)
    except SystemSpreadsheetError as exc:
        raise _error(422, "GOOGLE_SHEETS_IMPORT_FAILED", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.post("/system-spreadsheets/{spreadsheet_id}/connectors/google", summary="Anexa Google Sheets a uma planilha existente")
async def system_spreadsheet_attach_google(spreadsheet_id: str, payload: GoogleSpreadsheetPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        sheet = attach_google(sheet_id=spreadsheet_id, url_or_id=payload.url_or_id, tab=payload.tab)
    except SystemSpreadsheetError as exc:
        raise _error(422, "GOOGLE_SHEETS_CONNECTOR_FAILED", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet}


@router.get("/system-spreadsheets/google/config", summary="Status da conta de serviço Google")
async def system_spreadsheet_google_config(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return {"status": "ok", "configured": bool(connector_service_account_email()), "service_account_email": connector_service_account_email()}


@router.post("/system-spreadsheets/{spreadsheet_id}/sync/google", summary="Sincroniza uma planilha Google sem repetir ações")
async def system_spreadsheet_sync_google(spreadsheet_id: str, direction: str = Query(default="inbound", pattern="^(inbound|outbound)$"), _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        sheet = sync_google(spreadsheet_id, direction=direction)
    except SystemSpreadsheetError as exc:
        raise _error(422, "GOOGLE_SHEETS_SYNC_FAILED", str(exc)) from exc
    return {"status": "ok", "system_spreadsheet": sheet, "direction": direction}


@router.get("/data-sources/{source_id}", summary="Mostra schema de uma fonte")
async def data_source_detail(source_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    source = get_source(source_id)
    if source is None:
        raise _error(404, "DATA_SOURCE_NOT_FOUND", "Fonte de dados não encontrada.")
    return {"status": "ok", "data_source": source}


@router.post("/data-sources/schema", summary="Registra ou atualiza schema de fonte")
async def data_source_schema(payload: DataSourceSchemaPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        source = upsert_source_schema(name=payload.name, source_type=payload.source_type, headers=payload.headers, configuration=payload.configuration)
    except DataSourceError as exc:
        raise _error(422, "DATA_SOURCE_SCHEMA_INVALID", str(exc)) from exc
    return {"status": "ok", "data_source": source}


@router.get("/clients/export.csv", summary="Exporta clientes em CSV")
async def clients_export_csv(_user: AuthUser = Depends(require_user)) -> FastAPIResponse:
    try:
        clients = list_clients(include_inactive=True)
    except ClientsRepositoryError as exc:
        raise _error(500, "CLIENTS_UNAVAILABLE", str(exc)) from exc
    return FastAPIResponse(
        content=_clients_export_csv(clients),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="clientes_cotasync.csv"'},
    )


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


@router.delete("/actions/{action_id}", summary="Exclui ação definitivamente")
async def actions_delete(action_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        result = delete_or_archive_action(action_id)
    except ActionDeletionError as exc:
        raise _error(exc.status_code, exc.code, str(exc)) from exc
    except ActionsRepositoryError as exc:
        raise _error(500, "ACTION_DELETE_FAILED", str(exc)) from exc
    return {"status": "ok", **result}


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


@router.post("/actions/{action_id}/run", summary="Executa ação individual")
async def action_run(action_id: str, payload: ActionRunPayload, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    action = find_action(action_id)
    if action is None:
        raise _error(404, "ACTION_NOT_FOUND", "Acao nao encontrada.")
    missing = missing_required_variables(action, payload.variables)
    if missing:
        raise _error(422, "ACTION_VARIABLES_MISSING", f"Variaveis obrigatorias ausentes: {', '.join(missing)}.")
    try:
        if payload.mode == "async":
            run = start_action_run(action, payload)  # type: ignore[arg-type]
            schedule_finish_action_run(action, payload, run)  # type: ignore[arg-type]
        else:
            run = await run_action_sync(action, payload)  # type: ignore[arg-type]
    except RunsRepositoryError as exc:
        raise _error(500, "RUN_UNAVAILABLE", str(exc)) from exc
    return {"status": "ok", "run": run.model_dump()}


@router.get("/runs/{run_id}", summary="Consulta execução individual")
async def runs_get(run_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    run = get_run(run_id)
    if run is None:
        raise _error(404, "RUN_NOT_FOUND", "Execucao nao encontrada.")
    return {"status": "ok", "run": run.model_dump()}


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
        session = await demo_session_manager.recording_diagnostics(session_id)
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


class LearningResultSelectionRequest(BaseModel):
    target_name: str = ""
    screen_label: str = ""


class LearningResultSelectionConfirmRequest(BaseModel):
    target_name: str
    screen_label: str = ""
    selection_type: str = ""
    candidate: dict[str, Any] = Field(default_factory=dict)
    normalization: str = "exact_text"
    destination: dict[str, Any] | None = None


class LearningOutputRenameRequest(BaseModel):
    label: str


@router.post("/learning/sessions/{session_id}/result-selection/start", summary="Inicia seleção visual do resultado")
async def learning_start_result_selection(
    session_id: str,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        result = await demo_session_manager.start_result_selection(session_id)
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_RESULT_SELECTION_ERROR", str(exc)) from exc
    return {"status": "ok", "selection": result}


@router.post("/learning/sessions/{session_id}/result-selection/capture", summary="Captura seleção visual do resultado")
async def learning_capture_result_selection(
    session_id: str,
    payload: LearningResultSelectionRequest | None = None,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    request = payload or LearningResultSelectionRequest()
    try:
        result = await demo_session_manager.capture_result_selection(
            session_id,
            target_name=request.target_name,
            screen_label=request.screen_label,
        )
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_RESULT_SELECTION_ERROR", str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/learning/sessions/{session_id}/result-selection/confirm", summary="Confirma resultado selecionado")
async def learning_confirm_result_selection(
    session_id: str,
    payload: LearningResultSelectionConfirmRequest,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        result = await demo_session_manager.confirm_result_selection(
            session_id,
            target_name=payload.target_name,
            screen_label=payload.screen_label,
            candidate=payload.candidate,
            selection_type=payload.selection_type,
            normalization=payload.normalization,
            destination=payload.destination,
        )
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_RESULT_SELECTION_ERROR", str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/learning/sessions/{session_id}/result-selection/cancel", summary="Cancela seleção visual do resultado")
async def learning_cancel_result_selection(
    session_id: str,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        result = await demo_session_manager.cancel_result_selection(session_id)
    except DemoSessionError as exc:
        raise _error(409, "LEARNING_RESULT_SELECTION_ERROR", str(exc)) from exc
    return {"status": "ok", "selection": result}


@router.get("/learning/sessions/{session_id}/outputs", summary="Lista resultados do aprendizado")
async def learning_outputs(session_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        outputs = await demo_session_manager.learning_outputs(session_id)
    except DemoSessionError as exc:
        raise _error(404, "LEARNING_SESSION_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "outputs": outputs}


@router.post("/learning/sessions/{session_id}/ai-analysis", summary="Analisa aprendizado sem publicar automaticamente")
async def learning_ai_analysis(session_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        session = await demo_session_manager.recording_diagnostics(session_id)
    except DemoSessionError as exc:
        raise _error(404, "LEARNING_SESSION_NOT_FOUND", str(exc)) from exc
    events = session.get("learning_events") if isinstance(session.get("learning_events"), list) else []
    analysis = LearningAIObserver().analyze(build_raw_learning_trace(events))
    return {"status": "ok", "analysis": analysis, "published": False}


@router.patch("/learning/sessions/{session_id}/outputs/{output_id}", summary="Renomeia resultado do aprendizado")
async def learning_output_rename(session_id: str, output_id: str, payload: LearningOutputRenameRequest, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        output = await demo_session_manager.rename_learning_output(session_id, output_id, payload.label)
    except DemoSessionError as exc:
        raise _error(404, "LEARNING_OUTPUT_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "output": output}


@router.delete("/learning/sessions/{session_id}/outputs/{output_id}", summary="Remove resultado do aprendizado")
async def learning_output_remove(session_id: str, output_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        outputs = await demo_session_manager.remove_learning_output(session_id, output_id)
    except DemoSessionError as exc:
        raise _error(404, "LEARNING_OUTPUT_NOT_FOUND", str(exc)) from exc
    return {"status": "ok", "outputs": outputs}


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
            learning_mode=payload.learning_mode,
            data_source_id=payload.data_source_id,
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
    if payload.variable_key and isinstance(result, dict):
        result["variable_key"] = str(payload.variable_key)
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


@router.get("/browser/validate-view-token", summary="Valida token interno de visualizacao noVNC")
async def browser_validate_view_token(
    x_desktop_view_token: str | None = Header(default=None, alias="X-Desktop-View-Token"),
) -> FastAPIResponse:
    if not validate_token(x_desktop_view_token):
        raise _error(401, "DESKTOP_VIEW_TOKEN_INVALID", "Acesso nao autorizado.")
    return FastAPIResponse(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/browser/ensure-ready", summary="Verifica prontidão do browser")
async def browser_ensure_ready(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    health = await desktop_browser_health()
    if not health.get("cdp_reachable"):
        raise _error(503, "BROWSER_UNAVAILABLE", "Desktop browser indisponivel.")
    return {"status": "ok", "browser": health}


@router.get("/external-system/config", summary="Configuração do sistema externo")
async def external_system_config(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        config = load_current_external_system()
    except ExternalSystemConfigError as exc:
        raise _error(500, "EXTERNAL_SYSTEM_CONFIG_UNAVAILABLE", str(exc)) from exc
    return {"status": "ok", "external_system": _external_system_config_payload(config)}


@router.get("/settings/learning-ai", summary="Configuração da IA de aprendizado")
async def learning_ai_settings(_admin: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    return {"status": "ok", "learning_ai": public_settings()}


@router.put("/settings/learning-ai", summary="Salva configuração da IA de aprendizado")
async def learning_ai_settings_save(payload: AISettingsPayload, _admin: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    try:
        saved = save_settings(
            enabled=payload.enabled,
            provider=payload.provider,
            model=payload.model,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
    except ValueError as exc:
        raise _error(422, str(exc), "Verifique os campos da configuração da IA.") from exc
    return {"status": "ok", "learning_ai": saved}


@router.delete("/settings/learning-ai/key", summary="Remove explicitamente a chave da IA")
async def learning_ai_key_remove(_admin: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    return {"status": "ok", "learning_ai": remove_key()}


@router.post("/settings/learning-ai/test", summary="Testa conexão com a IA de aprendizado")
async def learning_ai_test(_admin: AuthUser = Depends(require_admin)) -> dict[str, Any]:
    settings = public_settings()
    if not settings["enabled"] or not settings["api_key_configured"]:
        raise _error(409, "AI_NOT_CONFIGURED", "Ative a IA e configure uma chave antes de testar.")
    result = LearningAIObserver().analyze([
        {"event": "click", "page_ref": "fixture-page", "selector": "#target-a", "before_selectors": ["#target-a"], "after_selectors": ["#target-a", "#target-b"], "next_target_selector": "#target-b"}
    ])
    if result.get("warnings") and not result.get("selector_analysis") and not result.get("transition_analysis") and not result.get("output_analysis") and not result.get("state_analysis"):
        raise _error(502, "AI_PROVIDER_UNAVAILABLE", "Não foi possível validar a conexão com a IA.")
    return {"status": "ok", "message": "Conexão funcionando"}


@router.put("/external-system/config", summary="Salva configuração do sistema externo")
async def external_system_config_save(
    payload: ExternalSystemConfigPayload,
    _admin: AuthUser = Depends(require_admin),
) -> dict[str, Any]:
    raw_login_url = str(payload.external_login_url or "")
    expected_host = str(payload.expected_system_host or "").strip()
    if raw_login_url and not expected_host:
        try:
            from urllib.parse import urlsplit

            expected_host = (urlsplit(raw_login_url.strip()).hostname or "").strip()
        except Exception:
            expected_host = ""
    try:
        config = save_current_external_system(
            {
                "external_system_name": payload.external_system_name,
                "external_login_url": raw_login_url,
                "access_profile_email_or_identifier": payload.access_profile_email_or_identifier,
                "microsoft_saved_account_identifier": payload.access_profile_email_or_identifier,
                "expected_system_host": expected_host,
            }
        )
    except ExternalSystemConfigError as exc:
        raise _error(422, "EXTERNAL_SYSTEM_CONFIG_INVALID", str(exc)) from exc
    return {"status": "ok", "external_system": _external_system_config_payload(config)}


@router.get("/external-session/status", summary="Status de sessão externa")
async def external_session_status(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    try:
        config = load_current_external_system()
    except ExternalSystemConfigError as exc:
        raise _error(500, "EXTERNAL_SESSION_UNAVAILABLE", str(exc)) from exc
    external_session = _external_session_payload(config)
    external_session["session_status"] = await _external_session_status_from_browser(config)
    return {"status": "ok", "external_session": external_session}


@router.post("/external-session/open-login", summary="Inicia explicitamente o login externo")
async def external_session_open_login(
    payload: ExternalSessionLoginPayload | None = None,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    config = load_current_external_system()
    login_url = str(config.get("external_login_url") or "")
    if not login_url:
        raise _error(422, "EXTERNAL_LOGIN_URL_MISSING", "URL de login externa nao configurada.")
    health = await desktop_browser_health()
    if not health.get("cdp_reachable"):
        raise _error(503, "BROWSER_UNAVAILABLE", "Desktop browser indisponivel.")
    force = bool(payload and payload.force)
    if not force and await _external_session_status_from_browser(config) == "authenticated":
        current_url = await _current_desktop_url()
        return {
            "status": "already_connected",
            "current_url": current_url,
            "manual_login_required": True,
            "browser_opened": False,
        }
    try:
        await _navigate_desktop_browser(login_url)
    except Exception as exc:
        raise _error(503, "BROWSER_NAVIGATION_FAILED", "Nao foi possivel abrir a URL de login no navegador.") from exc
    return {
        "status": "login_started",
        "login_url": login_url,
        "manual_login_required": True,
        "browser_opened": True,
    }


@router.post("/external-session/validate", summary="Valida configuração de sessão externa")
async def external_session_validate(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    config = load_current_external_system()
    external_session = _external_session_payload(config)
    external_session["session_status"] = await _external_session_status_from_browser(config)
    return {
        "status": "ok",
        "valid": external_session["session_status"] == "authenticated",
        "configuration_valid": bool(external_session["external_system_configured"]),
        "session_status": external_session["session_status"],
        "manual_login_required": True,
        "external_session": external_session,
    }


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


@router.post("/batches/{batch_id}/resume", summary="Retoma item do batch aguardando atenção")
async def batches_resume(batch_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    batch = resume_batch(batch_id)
    if batch is None:
        raise _error(409, "BATCH_NOT_RESUMABLE", "Este lote não possui item aguardando atenção para retomar.")
    return {"status": "ok", "batch": batch}


@router.get("/batches/{batch_id}/results", summary="Resultados CSV do batch")
async def batches_results(batch_id: str, _user: AuthUser = Depends(require_user)) -> FastAPIResponse:
    batch = load_batch(batch_id)
    if batch is None:
        raise _error(404, "BATCH_NOT_FOUND", "Batch nao encontrado.")
    return FastAPIResponse(content=batch_results_csv(batch), media_type="text/csv; charset=utf-8")


@router.get("/batches/{batch_id}/results.csv", summary="Resultados CSV do batch")
async def batches_results_csv_alias(batch_id: str, _user: AuthUser = Depends(require_user)) -> FastAPIResponse:
    return await batches_results(batch_id, _user)


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
    client: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    _user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        runs = [run.model_dump() for run in list_runs(action_id=action_id, status=status, limit=500)]  # type: ignore[arg-type]
    except RunsRepositoryError as exc:
        raise _error(500, "RUNS_UNAVAILABLE", str(exc)) from exc
    if run_origin:
        runs = [run for run in runs if run.get("run_origin") == run_origin]
    runs = [run for run in runs if _run_matches_filters(run, client=client, date_from=date_from, date_to=date_to)]
    return {"status": "ok", "runs": _paginate(runs, page, page_size)}


@router.get("/reports/runs.csv", summary="Exporta histórico filtrado de runs em CSV")
async def reports_runs_csv(
    action_id: str | None = None,
    status: str | None = None,
    run_origin: str | None = None,
    client: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    _user: AuthUser = Depends(require_user),
) -> FastAPIResponse:
    try:
        runs = [run.model_dump() for run in list_runs(action_id=action_id, status=status, limit=500)]  # type: ignore[arg-type]
    except RunsRepositoryError as exc:
        raise _error(500, "RUNS_UNAVAILABLE", str(exc)) from exc
    if run_origin:
        runs = [run for run in runs if run.get("run_origin") == run_origin]
    runs = [run for run in runs if _run_matches_filters(run, client=client, date_from=date_from, date_to=date_to)]
    return FastAPIResponse(
        content=_runs_csv(runs),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="execucoes_cotasync.csv"'},
    )


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
