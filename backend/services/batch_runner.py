from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.db import Action as DbAction, ActionVersion, Batch as DbBatch, BatchItem, Client as DbClient, SessionLocal
from backend.services.action_runner import missing_required_variables, run_action_sync
from backend.services.actions_repository import find_action, project_root
from backend.services.clients_repository import validate_clients_for_action

logger = logging.getLogger("cotasync.batch_runner")

BatchStatus = str
RowStatus = str

FINAL_BATCH_STATUSES = {"success", "partial_success", "error", "canceled"}
RUNNING_BATCH_STATUSES = {"pending", "running"}
DEFAULT_DELAY_BETWEEN_ROWS_SECONDS = 3

_desktop_batch_lock = asyncio.Lock()
_worker_tasks: set[asyncio.Task] = set()


class BatchRunnerError(Exception):
    """Erro controlado no gerenciamento da fila sequencial de batches."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

def _parse_batch_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def default_batches_dir() -> Path:
    return project_root() / "data" / "batches"


def _batch_path(batch_id: str, batches_dir: Path | None = None) -> Path:
    return (batches_dir or default_batches_dir()) / f"{batch_id}.json"


def parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
    text = str(csv_text or "")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    if not text.strip():
        return []

    stream = io.StringIO(text)
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        return []

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        if raw_row is None:
            continue
        normalized = {
            str(key or "").lstrip("\ufeff").strip(): "" if value is None else str(value)
            for key, value in raw_row.items()
            if key is not None and str(key).strip()
        }
        if any(str(value).strip() for value in normalized.values()):
            rows.append(normalized)
    return rows


def required_variable_keys(action: Any) -> list[str]:
    keys: list[str] = []
    for variable in getattr(action, "variables", []) or []:
        if bool(getattr(variable, "required", True)):
            key = str(getattr(variable, "key", "") or "").strip()
            if key:
                keys.append(key)
    return keys


def validate_batch_rows(action: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise BatchRunnerError("CSV sem linhas para executar.")

    required = required_variable_keys(action)
    columns: set[str] = set()
    for row in rows:
        columns.update(str(key) for key in row.keys())
    missing_columns = [key for key in required if key not in columns]
    if missing_columns:
        raise BatchRunnerError(
            "CSV sem colunas obrigatorias: " + ", ".join(missing_columns)
        )

    row_errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        missing_values = [
            key for key in required if row.get(key) is None or not str(row.get(key)).strip()
        ]
        if missing_values:
            row_errors.append(f"linha {index}: {', '.join(missing_values)}")
    if row_errors:
        raise BatchRunnerError("Variaveis obrigatorias ausentes no lote: " + "; ".join(row_errors))


def _prepared_variables(row: dict[str, Any]) -> dict[str, Any]:
    variables = row.get("variables") if isinstance(row.get("variables"), dict) else row
    return variables if isinstance(variables, dict) else {}


def _validate_prepared_rows(action: Any, rows: list[dict[str, Any]]) -> None:
    validate_batch_rows(action, [_prepared_variables(row) for row in rows])


def _rows_from_clients(
    action: Any,
    *,
    client_group: str | None = None,
    client_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    validation = validate_clients_for_action(action, client_group=client_group, client_ids=client_ids)
    ready = validation.get("ready") if isinstance(validation, dict) else []
    rows: list[dict[str, Any]] = []
    for client in ready if isinstance(ready, list) else []:
        if not isinstance(client, dict):
            continue
        variables = client.get("variables") if isinstance(client.get("variables"), dict) else {}
        rows.append(
            {
                "client_id": str(client.get("id") or ""),
                "client_name": str(client.get("name") or ""),
                "client_group": str(client.get("group") or ""),
                "variables": {str(key): str(value) for key, value in variables.items()},
            }
        )
    return rows


def _write_batch(batch: dict[str, Any], batches_dir: Path | None = None) -> dict[str, Any]:
    if batches_dir is None:
        with SessionLocal.begin() as session:
            action = session.get(DbAction, str(batch.get("action_id") or ""))
            db_batch = session.get(DbBatch, str(batch["batch_id"]))
            rows = batch.get("rows") if isinstance(batch.get("rows"), list) else []
            if db_batch is None:
                db_batch = DbBatch(id=str(batch["batch_id"]), action_id=action.id if action else None, client_group=str(batch.get("client_group") or "") or None, status=str(batch.get("status") or "pending"), delay_seconds=float(batch.get("delay_between_rows_seconds") or 0), total_items=len(rows), created_by=str(batch.get("requested_by") or "") or None, metadata_json={"source": batch.get("source"), "action_key": batch.get("action_key")})
                session.add(db_batch)
            db_batch.status = str(batch.get("status") or db_batch.status)
            db_batch.cancel_requested = bool(batch.get("cancel_requested", False))
            db_batch.started_at = _parse_batch_dt(batch.get("started_at"))
            db_batch.finished_at = _parse_batch_dt(batch.get("finished_at"))
            db_batch.processed_items = sum(1 for row in rows if isinstance(row, dict) and row.get("status") in {"success", "error"})
            db_batch.success_items = sum(1 for row in rows if isinstance(row, dict) and row.get("status") == "success")
            db_batch.error_items = sum(1 for row in rows if isinstance(row, dict) and row.get("status") == "error")
            session.flush()
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                item_id = f"{db_batch.id}-item-{index-1}"
                item = session.get(BatchItem, item_id)
                if item is None:
                    item = BatchItem(id=item_id, batch_id=db_batch.id, position=index)
                    session.add(item)
                item.client_id = str(row.get("client_id") or "") or None
                item.status = str(row.get("status") or "pending")
                item.run_id = str(row.get("run_id") or "") or None
                item.input_variables = _prepared_variables(row)
                item.result_data = row.get("result_payload") if isinstance(row.get("result_payload"), dict) else {}
                item.error_data = {"message": row.get("error_message")} if row.get("error_message") else {}
                item.started_at = _parse_batch_dt(row.get("started_at"))
                item.finished_at = _parse_batch_dt(row.get("finished_at"))
        return batch
    path = _batch_path(str(batch["batch_id"]), batches_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            json.dump(batch, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    except OSError as exc:
        raise BatchRunnerError("Nao foi possivel salvar o batch.") from exc
    return batch


def load_batch(batch_id: str, batches_dir: Path | None = None) -> dict[str, Any] | None:
    if batches_dir is None:
        with SessionLocal() as session:
            db_batch = session.get(DbBatch, str(batch_id))
            if db_batch is None:
                return None
            items = session.query(BatchItem).filter(BatchItem.batch_id == db_batch.id).order_by(BatchItem.position).all()
            return {"batch_id": db_batch.id, "action_id": db_batch.action_id or "", "status": db_batch.status, "requested_by": db_batch.created_by or "api", "client_group": db_batch.client_group or "", "delay_between_rows_seconds": db_batch.delay_seconds, "created_at": db_batch.created_at.isoformat() if db_batch.created_at else None, "started_at": db_batch.started_at.isoformat() if db_batch.started_at else None, "finished_at": db_batch.finished_at.isoformat() if db_batch.finished_at else None, "cancel_requested": db_batch.cancel_requested, "rows": [{"index": item.position, "client_id": item.client_id or "", "status": item.status, "run_id": item.run_id or "", "variables": item.input_variables or {}, "result_payload": item.result_data or {}, "error_message": (item.error_data or {}).get("message", ""), "started_at": item.started_at.isoformat() if item.started_at else None, "finished_at": item.finished_at.isoformat() if item.finished_at else None} for item in items]}
    path = _batch_path(batch_id, batches_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BatchRunnerError("Batch persistido invalido.") from exc
    if not isinstance(payload, dict):
        raise BatchRunnerError("Batch persistido deve ser um objeto JSON.")
    return payload


def list_batches(*, limit: int = 20, batches_dir: Path | None = None) -> list[dict[str, Any]]:
    if batches_dir is None:
        with SessionLocal() as session:
            rows = session.query(DbBatch).order_by(DbBatch.created_at.desc()).limit(max(0, min(int(limit), 200))).all()
            return [load_batch(row.id, None) for row in rows if load_batch(row.id, None) is not None]
    root = batches_dir or default_batches_dir()
    if not root.exists():
        return []
    batches: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Batch ignorado por JSON invalido: %s", path)
            continue
        if isinstance(payload, dict):
            batches.append(payload)
        if len(batches) >= max(0, min(int(limit), 200)):
            break
    return batches


def find_running_batch(batches_dir: Path | None = None) -> dict[str, Any] | None:
    for batch in list_batches(limit=200, batches_dir=batches_dir):
        if str(batch.get("status") or "") in RUNNING_BATCH_STATUSES:
            return batch
    return None


def _row_result_from_run(row: dict[str, Any], run: RunRecord) -> dict[str, Any]:
    payload = run.result_payload if isinstance(run.result_payload, dict) else {}
    dados_extraidos = payload.get("dados_extraidos") if isinstance(payload, dict) else {}
    return {
        **row,
        "status": run.status,
        "run_id": run.id,
        "operational_summary": run.operational_summary or run.result_summary or "",
        "result_payload": payload,
        "dados_extraidos": dados_extraidos if isinstance(dados_extraidos, dict) else {},
        "error_message": run.error_message or "",
        "finished_at": run.finished_at,
    }


def _final_status(rows: list[dict[str, Any]], cancel_requested: bool) -> BatchStatus:
    if cancel_requested:
        return "canceled"
    success_count = sum(1 for row in rows if row.get("status") == "success")
    error_count = sum(1 for row in rows if row.get("status") == "error")
    if success_count and error_count:
        return "partial_success"
    if success_count and not error_count:
        return "success"
    return "error"


async def _run_batch_worker(batch_id: str, *, batches_dir: Path | None = None) -> None:
    async with _desktop_batch_lock:
        batch = load_batch(batch_id, batches_dir)
        if batch is None:
            return
        if str(batch.get("status") or "") not in RUNNING_BATCH_STATUSES:
            return

        try:
            action = find_action(str(batch.get("action_id") or ""))
            if action is None:
                raise BatchRunnerError("Acao nao encontrada para executar o batch.")

            batch["status"] = "running"
            batch["started_at"] = batch.get("started_at") or utc_now_iso()
            _write_batch(batch, batches_dir)

            rows = batch.get("rows") if isinstance(batch.get("rows"), list) else []
            delay_seconds = max(0, float(batch.get("delay_between_rows_seconds") or 0))
            for index, row in enumerate(rows):
                batch = load_batch(batch_id, batches_dir) or batch
                rows = batch.get("rows") if isinstance(batch.get("rows"), list) else rows
                if bool(batch.get("cancel_requested")):
                    for pending_row in rows[index:]:
                        if pending_row.get("status") == "pending":
                            pending_row["status"] = "skipped"
                            pending_row["finished_at"] = utc_now_iso()
                    break

                row = rows[index]
                row["status"] = "running"
                row["started_at"] = utc_now_iso()
                _write_batch(batch, batches_dir)

                variables = row.get("variables") if isinstance(row.get("variables"), dict) else {}
                request = ActionRunRequest(
                    variables=variables,
                    mode="sync",
                    requested_by=str(batch.get("requested_by") or "batch"),
                )
                try:
                    missing = missing_required_variables(action, request.variables)
                    if missing:
                        raise BatchRunnerError("Variaveis obrigatorias ausentes: " + ", ".join(missing))
                    run = await run_action_sync(action, request)
                    rows[index] = _row_result_from_run(row, run)
                except Exception as exc:
                    rows[index] = {
                        **row,
                        "status": "error",
                        "error_message": str(exc)[:1000] or type(exc).__name__,
                        "finished_at": utc_now_iso(),
                    }
                batch["rows"] = rows
                _write_batch(batch, batches_dir)

                if index < len(rows) - 1 and not bool(batch.get("cancel_requested")) and delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

            batch = load_batch(batch_id, batches_dir) or batch
            rows = batch.get("rows") if isinstance(batch.get("rows"), list) else []
            batch["status"] = _final_status(rows, bool(batch.get("cancel_requested")))
            batch["finished_at"] = utc_now_iso()
            _write_batch(batch, batches_dir)
        except Exception as exc:
            logger.exception("Falha critica no batch %s", batch_id)
            batch = load_batch(batch_id, batches_dir) or {"batch_id": batch_id, "rows": []}
            batch["status"] = "error"
            batch["error_message"] = str(exc)[:1000] or type(exc).__name__
            batch["finished_at"] = utc_now_iso()
            _write_batch(batch, batches_dir)


def schedule_batch_worker(batch_id: str, *, batches_dir: Path | None = None) -> None:
    task = asyncio.create_task(_run_batch_worker(batch_id, batches_dir=batches_dir))
    _worker_tasks.add(task)
    task.add_done_callback(_worker_tasks.discard)


def create_batch(
    *,
    action_id: str,
    rows: list[dict[str, Any]] | None = None,
    client_group: str | None = None,
    client_ids: list[str] | None = None,
    requested_by: str = "api",
    delay_between_rows_seconds: int | float = DEFAULT_DELAY_BETWEEN_ROWS_SECONDS,
    batches_dir: Path | None = None,
    auto_start: bool = True,
) -> dict[str, Any]:
    active = find_running_batch(batches_dir)
    if active is not None:
        raise BatchRunnerError(
            f"Ja existe um lote em execucao no desktop/session: {active.get('batch_id')}"
        )

    action = find_action(action_id)
    if action is None:
        raise BatchRunnerError("Acao nao encontrada.")
    source = "rows"
    prepared_rows = rows or []
    if client_group or client_ids:
        source = "clients"
        prepared_rows = _rows_from_clients(action, client_group=client_group, client_ids=client_ids)
        if not prepared_rows:
            raise BatchRunnerError("Nenhum cliente ativo com dados completos para esta acao.")
    _validate_prepared_rows(action, prepared_rows)

    batch_id = str(uuid4())
    created_at = utc_now_iso()
    batch = {
        "batch_id": batch_id,
        "action_id": action.id,
        "action_key": action.key,
        "status": "pending",
        "requested_by": str(requested_by or "api"),
        "source": source,
        "client_group": str(client_group or ""),
        "client_ids": [str(item) for item in client_ids or []],
        "delay_between_rows_seconds": max(0, float(delay_between_rows_seconds)),
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "rows": [
            {
                "index": index,
                "client_id": str(row.get("client_id") or ""),
                "client_name": str(row.get("client_name") or ""),
                "client_group": str(row.get("client_group") or ""),
                "variables": {str(key): str(value) for key, value in _prepared_variables(row).items()},
                "status": "pending",
                "run_id": "",
                "operational_summary": "",
                "result_payload": {},
                "dados_extraidos": {},
                "error_message": "",
                "started_at": None,
                "finished_at": None,
            }
            for index, row in enumerate(prepared_rows, start=1)
        ],
    }
    _write_batch(batch, batches_dir)
    if auto_start:
        schedule_batch_worker(batch_id, batches_dir=batches_dir)
    return batch


def cancel_batch(batch_id: str, batches_dir: Path | None = None) -> dict[str, Any]:
    batch = load_batch(batch_id, batches_dir)
    if batch is None:
        raise BatchRunnerError("Batch nao encontrado.")
    if str(batch.get("status") or "") in FINAL_BATCH_STATUSES:
        return batch
    batch["cancel_requested"] = True
    _write_batch(batch, batches_dir)
    return batch


def batch_results_csv(batch: dict[str, Any]) -> str:
    output = io.StringIO()
    columns = [
        "batch_id",
        "row_index",
        "client_id",
        "client_name",
        "client_group",
        "action_id",
        "status",
        "run_id",
        "variables_json",
        "operational_summary",
        "dados_extraidos_json",
        "error_message",
        "started_at",
        "finished_at",
    ]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    rows = batch.get("rows") if isinstance(batch.get("rows"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result_payload = row.get("result_payload") if isinstance(row.get("result_payload"), dict) else {}
        dados_extraidos = row.get("dados_extraidos")
        if not isinstance(dados_extraidos, dict) and isinstance(result_payload, dict):
            dados_extraidos = result_payload.get("dados_extraidos")
        writer.writerow(
            {
                "batch_id": batch.get("batch_id", ""),
                "row_index": row.get("index", ""),
                "client_id": row.get("client_id", ""),
                "client_name": row.get("client_name", ""),
                "client_group": row.get("client_group", ""),
                "action_id": batch.get("action_id", ""),
                "status": row.get("status", ""),
                "run_id": row.get("run_id", ""),
                "variables_json": json.dumps(row.get("variables") or {}, ensure_ascii=False, sort_keys=True),
                "operational_summary": row.get("operational_summary", ""),
                "dados_extraidos_json": json.dumps(dados_extraidos or {}, ensure_ascii=False, sort_keys=True),
                "error_message": row.get("error_message", ""),
                "started_at": row.get("started_at", ""),
                "finished_at": row.get("finished_at", ""),
            }
        )
    return output.getvalue()
