from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import Action as DbAction, Batch as DbBatch, BatchItem, Client as DbClient, Run as DbRun, SessionLocal
from backend.services.actions_repository import find_action
from backend.services.clients_repository import validate_clients_for_action

logger = logging.getLogger("cotasync.batch_runner")

BatchStatus = str
RowStatus = str

BATCH_STATUS_QUEUED = "queued"
BATCH_STATUS_RUNNING = "running"
BATCH_STATUS_CANCEL_REQUESTED = "cancel_requested"
BATCH_STATUS_CANCELLED = "cancelled"
BATCH_STATUS_COMPLETED = "completed"
BATCH_STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
BATCH_STATUS_INTERRUPTED = "interrupted"
BATCH_STATUS_FAILED = "failed"

ITEM_STATUS_PENDING = "pending"
ITEM_STATUS_RUNNING = "running"
ITEM_STATUS_SUCCESS = "success"
ITEM_STATUS_ERROR = "error"
ITEM_STATUS_INTERRUPTED = "interrupted"
ITEM_STATUS_CANCELLED = "cancelled"

FINAL_BATCH_STATUSES = {
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_COMPLETED,
    BATCH_STATUS_COMPLETED_WITH_ERRORS,
    BATCH_STATUS_INTERRUPTED,
    BATCH_STATUS_FAILED,
    "success",
    "partial_success",
    "error",
    "canceled",
}
RUNNING_BATCH_STATUSES = {BATCH_STATUS_QUEUED, BATCH_STATUS_RUNNING, BATCH_STATUS_CANCEL_REQUESTED, "pending"}
PROCESSED_ITEM_STATUSES = {ITEM_STATUS_SUCCESS, ITEM_STATUS_ERROR, ITEM_STATUS_INTERRUPTED, ITEM_STATUS_CANCELLED}
DEFAULT_DELAY_BETWEEN_ROWS_SECONDS = 3


class BatchRunnerError(Exception):
    """Erro controlado no gerenciamento da fila sequencial de batches."""


class BatchIdempotencyConflict(BatchRunnerError):
    """Idempotency-Key reutilizada com payload diferente no mesmo escopo."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def _parse_batch_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalize_batch_status(status: str) -> str:
    return {
        "pending": BATCH_STATUS_QUEUED,
        "success": BATCH_STATUS_COMPLETED,
        "partial_success": BATCH_STATUS_COMPLETED_WITH_ERRORS,
        "error": BATCH_STATUS_FAILED,
        "canceled": BATCH_STATUS_CANCELLED,
    }.get(str(status or "").strip(), str(status or "").strip() or BATCH_STATUS_QUEUED)


def _normalize_item_status(status: str) -> str:
    return {"skipped": ITEM_STATUS_CANCELLED}.get(str(status or "").strip(), str(status or "").strip() or ITEM_STATUS_PENDING)


def parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
    text_value = str(csv_text or "")
    if text_value.startswith("\ufeff"):
        text_value = text_value.lstrip("\ufeff")
    if not text_value.strip():
        return []

    reader = csv.DictReader(io.StringIO(text_value))
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
        raise BatchRunnerError("CSV sem colunas obrigatorias: " + ", ".join(missing_columns))

    row_errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        missing_values = [key for key in required if row.get(key) is None or not str(row.get(key)).strip()]
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


def _item_id(batch_id: str, position: int) -> str:
    return f"{batch_id}-item-{position - 1}"


def batch_idempotency_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_payload(
    *,
    action_id: str,
    source: str,
    client_group: str | None,
    client_ids: list[str] | None,
    rows: list[dict[str, Any]],
    delay_between_rows_seconds: int | float,
) -> dict[str, Any]:
    return {
        "operation": "batch:create",
        "action_id": str(action_id or ""),
        "source": str(source or ""),
        "client_group": str(client_group or ""),
        "client_ids": [str(item) for item in client_ids or []],
        "delay_between_rows_seconds": max(0, float(delay_between_rows_seconds)),
        "rows": [
            {
                "client_id": str(row.get("client_id") or ""),
                "variables": {str(key): str(value) for key, value in _prepared_variables(row).items()},
            }
            for row in rows
        ],
    }


def _load_existing_idempotent_batch(
    *,
    user_id: str,
    operation: str,
    key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    with SessionLocal() as session:
        existing = (
            session.query(DbBatch)
            .filter(
                DbBatch.idempotency_user_id == user_id,
                DbBatch.idempotency_operation == operation,
                DbBatch.idempotency_key == key,
            )
            .first()
        )
        if existing is None:
            return None
        if existing.idempotency_fingerprint != fingerprint:
            raise BatchIdempotencyConflict("Idempotency-Key ja utilizada com payload diferente.")
        return load_batch(existing.id)


def _recount_batch(session: Any, batch_id: str) -> None:
    batch = session.get(DbBatch, batch_id)
    if batch is None:
        return
    items = session.query(BatchItem).filter(BatchItem.batch_id == batch_id).all()
    batch.total_items = len(items)
    batch.processed_items = sum(1 for item in items if item.status in PROCESSED_ITEM_STATUSES)
    batch.success_items = sum(1 for item in items if item.status == ITEM_STATUS_SUCCESS)
    batch.error_items = sum(1 for item in items if item.status == ITEM_STATUS_ERROR)
    batch.interrupted_items = sum(1 for item in items if item.status == ITEM_STATUS_INTERRUPTED)
    batch.cancelled_items = sum(1 for item in items if item.status == ITEM_STATUS_CANCELLED)


def _batch_final_status(items: list[BatchItem], *, cancel_requested: bool = False) -> str:
    if cancel_requested:
        return BATCH_STATUS_CANCELLED
    statuses = [item.status for item in items]
    if statuses and all(status == ITEM_STATUS_SUCCESS for status in statuses):
        return BATCH_STATUS_COMPLETED
    if any(status in {ITEM_STATUS_SUCCESS, ITEM_STATUS_ERROR, ITEM_STATUS_INTERRUPTED, ITEM_STATUS_CANCELLED} for status in statuses):
        return BATCH_STATUS_COMPLETED_WITH_ERRORS
    return BATCH_STATUS_FAILED


def _batch_to_dict(db_batch: DbBatch, items: list[BatchItem]) -> dict[str, Any]:
    current = next((item for item in items if item.status == ITEM_STATUS_RUNNING), None)
    return {
        "batch_id": db_batch.id,
        "action_id": db_batch.action_id or "",
        "action_version_id": db_batch.action_version_id or "",
        "status": _normalize_batch_status(db_batch.status),
        "requested_by": db_batch.created_by or "api",
        "client_group": db_batch.client_group or "",
        "delay_between_rows_seconds": db_batch.delay_seconds,
        "created_at": db_batch.created_at.isoformat() if db_batch.created_at else None,
        "started_at": db_batch.started_at.isoformat() if db_batch.started_at else None,
        "finished_at": db_batch.finished_at.isoformat() if db_batch.finished_at else None,
        "heartbeat_at": db_batch.heartbeat_at.isoformat() if db_batch.heartbeat_at else None,
        "worker_id": db_batch.worker_id or "",
        "cancel_requested": db_batch.cancel_requested,
        "idempotency_key": db_batch.idempotency_key or "",
        "idempotency_user_id": db_batch.idempotency_user_id or "",
        "idempotency_operation": db_batch.idempotency_operation or "",
        "total_items": db_batch.total_items,
        "processed_items": db_batch.processed_items,
        "success_items": db_batch.success_items,
        "error_items": db_batch.error_items,
        "interrupted_items": db_batch.interrupted_items,
        "cancelled_items": db_batch.cancelled_items,
        "current_position": current.position if current else None,
        "current_client_id": current.client_id if current else None,
        "metadata": db_batch.metadata_json or {},
        "source": (db_batch.metadata_json or {}).get("source", ""),
        "client_ids": (db_batch.metadata_json or {}).get("client_ids", []),
        "rows": [
            {
                "index": item.position,
                "client_id": item.client_id or "",
                "client_name": "",
                "client_group": "",
                "status": _normalize_item_status(item.status),
                "run_id": item.run_id or "",
                "variables": item.input_variables or {},
                "result_payload": item.result_data or {},
                "dados_extraidos": (item.result_data or {}).get("dados_extraidos", {}) if isinstance(item.result_data, dict) else {},
                "error_message": (item.error_data or {}).get("message", ""),
                "error_data": item.error_data or {},
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
                "retry_count": item.retry_count,
            }
            for item in items
        ],
    }


def load_batch(batch_id: str, batches_dir: Path | None = None) -> dict[str, Any] | None:
    with SessionLocal.begin() as session:
        db_batch = session.get(DbBatch, str(batch_id))
        if db_batch is None:
            return None
        items = session.query(BatchItem).filter(BatchItem.batch_id == db_batch.id).order_by(BatchItem.position).all()
        _recount_batch(session, db_batch.id)
        return _batch_to_dict(db_batch, items)


def list_batches(*, limit: int = 20, batches_dir: Path | None = None) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.query(DbBatch).order_by(DbBatch.created_at.desc()).limit(max(0, min(int(limit), 200))).all()
        result: list[dict[str, Any]] = []
        for row in rows:
            items = session.query(BatchItem).filter(BatchItem.batch_id == row.id).order_by(BatchItem.position).all()
            result.append(_batch_to_dict(row, items))
        return result


def find_running_batch(batches_dir: Path | None = None) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = (
            session.query(DbBatch)
            .filter(DbBatch.status.in_([BATCH_STATUS_RUNNING, BATCH_STATUS_CANCEL_REQUESTED]))
            .order_by(DbBatch.created_at)
            .first()
        )
        if row is None:
            return None
    return load_batch(row.id)


def create_batch(
    *,
    action_id: str,
    rows: list[dict[str, Any]] | None = None,
    client_group: str | None = None,
    client_ids: list[str] | None = None,
    requested_by: str = "api",
    delay_between_rows_seconds: int | float = DEFAULT_DELAY_BETWEEN_ROWS_SECONDS,
    batches_dir: Path | None = None,
    auto_start: bool = False,
    idempotency_key: str | None = None,
    idempotency_user_id: str | None = None,
    idempotency_operation: str = "batch:create",
) -> dict[str, Any]:
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

    normalized_key = str(idempotency_key or "").strip() or None
    normalized_user_id = str(idempotency_user_id or requested_by or "anonymous").strip() or "anonymous"
    operation = str(idempotency_operation or "batch:create").strip() or "batch:create"
    fingerprint_payload = _idempotency_payload(
        action_id=action.id,
        source=source,
        client_group=client_group,
        client_ids=client_ids,
        rows=prepared_rows,
        delay_between_rows_seconds=delay_between_rows_seconds,
    )
    fingerprint = batch_idempotency_fingerprint(fingerprint_payload)
    if normalized_key:
        existing = _load_existing_idempotent_batch(
            user_id=normalized_user_id,
            operation=operation,
            key=normalized_key,
            fingerprint=fingerprint,
        )
        if existing is not None:
            return existing

    batch_id = str(uuid4())
    created_at = utc_now_iso()
    batch = {
        "batch_id": batch_id,
        "action_id": action.id,
        "action_key": action.key,
        "status": BATCH_STATUS_QUEUED,
        "requested_by": str(requested_by or "api"),
        "source": source,
        "client_group": str(client_group or ""),
        "client_ids": [str(item) for item in client_ids or []],
        "delay_between_rows_seconds": max(0, float(delay_between_rows_seconds)),
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "idempotency_key": normalized_key,
        "rows": [
            {
                "index": index,
                "client_id": str(row.get("client_id") or ""),
                "client_name": str(row.get("client_name") or ""),
                "client_group": str(row.get("client_group") or ""),
                "variables": {str(key): str(value) for key, value in _prepared_variables(row).items()},
                "status": ITEM_STATUS_PENDING,
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
    try:
        with SessionLocal.begin() as session:
            db_batch = DbBatch(
                id=batch_id,
                action_id=action.id,
                action_version_id=getattr(action, "published_version_id", None),
                client_group=str(client_group or "") or None,
                status=BATCH_STATUS_QUEUED,
                delay_seconds=max(0, float(delay_between_rows_seconds)),
                total_items=len(batch["rows"]),
                created_by=str(requested_by or "") or None,
                idempotency_key=normalized_key,
                idempotency_user_id=normalized_user_id if normalized_key else None,
                idempotency_operation=operation if normalized_key else None,
                idempotency_fingerprint=fingerprint if normalized_key else None,
                metadata_json={"source": source, "action_key": action.key, "client_ids": batch["client_ids"]},
            )
            session.add(db_batch)
            session.flush()
            for row in batch["rows"]:
                position = int(row["index"])
                client_id = str(row.get("client_id") or "") or None
                item = BatchItem(
                    id=_item_id(batch_id, position),
                    batch_id=batch_id,
                    client_id=client_id if client_id and session.get(DbClient, client_id) is not None else None,
                    position=position,
                    status=ITEM_STATUS_PENDING,
                    input_variables=row["variables"],
                    result_data={},
                    error_data={},
                )
                session.add(item)
    except IntegrityError as exc:
        if normalized_key:
            existing = _load_existing_idempotent_batch(
                user_id=normalized_user_id,
                operation=operation,
                key=normalized_key,
                fingerprint=fingerprint,
            )
            if existing is not None:
                return existing
        raise BatchRunnerError("Falha de idempotencia ao criar batch.") from exc
    loaded = load_batch(batch_id)
    if loaded is None:
        return batch
    loaded["source"] = source
    loaded["client_ids"] = batch["client_ids"]
    loaded_rows = loaded.get("rows") if isinstance(loaded.get("rows"), list) else []
    for index, original in enumerate(batch["rows"]):
        if index < len(loaded_rows) and isinstance(loaded_rows[index], dict):
            loaded_rows[index]["client_name"] = original.get("client_name", "")
            loaded_rows[index]["client_group"] = original.get("client_group", "")
            if original.get("client_id"):
                loaded_rows[index]["client_id"] = original.get("client_id", "")
    return loaded


def cancel_batch(batch_id: str, batches_dir: Path | None = None) -> dict[str, Any]:
    with SessionLocal.begin() as session:
        batch = session.get(DbBatch, str(batch_id))
        if batch is None:
            raise BatchRunnerError("Batch nao encontrado.")
        batch.status = _normalize_batch_status(batch.status)
        if batch.status in FINAL_BATCH_STATUSES:
            pass
        else:
            running = (
                session.query(BatchItem)
                .filter(BatchItem.batch_id == batch.id, BatchItem.status == ITEM_STATUS_RUNNING)
                .first()
            )
            batch.cancel_requested = True
            if running is None:
                now = utc_now()
                (
                    session.query(BatchItem)
                    .filter(BatchItem.batch_id == batch.id, BatchItem.status == ITEM_STATUS_PENDING)
                    .update({BatchItem.status: ITEM_STATUS_CANCELLED, BatchItem.finished_at: now}, synchronize_session=False)
                )
                batch.status = BATCH_STATUS_CANCELLED
                batch.finished_at = now
            else:
                batch.status = BATCH_STATUS_CANCEL_REQUESTED
            _recount_batch(session, batch.id)
    loaded = load_batch(batch_id)
    if loaded is None:
        raise BatchRunnerError("Batch nao encontrado.")
    return loaded


def claim_next_batch(worker_id: str) -> str | None:
    now = utc_now()
    with SessionLocal.begin() as session:
        row = session.execute(
            text(
                """
                select id
                  from batches
                 where status = :queued
                 order by created_at asc, id asc
                 for update skip locked
                 limit 1
                """
            ),
            {"queued": BATCH_STATUS_QUEUED},
        ).first()
        if row is None:
            return None
        batch = session.get(DbBatch, row.id)
        if batch is None:
            return None
        batch.status = BATCH_STATUS_RUNNING
        batch.worker_id = worker_id
        batch.started_at = batch.started_at or now
        batch.heartbeat_at = now
        return batch.id


def claim_next_item(batch_id: str) -> str | None:
    now = utc_now()
    with SessionLocal.begin() as session:
        batch = session.get(DbBatch, batch_id)
        if batch is None or batch.status not in {BATCH_STATUS_RUNNING, BATCH_STATUS_CANCEL_REQUESTED}:
            return None
        if batch.cancel_requested or batch.status == BATCH_STATUS_CANCEL_REQUESTED:
            cancel_pending_items(session, batch_id)
            batch.status = BATCH_STATUS_CANCELLED
            batch.finished_at = now
            _recount_batch(session, batch_id)
            return None
        running_count = (
            session.query(BatchItem)
            .filter(BatchItem.batch_id == batch_id, BatchItem.status == ITEM_STATUS_RUNNING)
            .count()
        )
        if running_count:
            return None
        row = session.execute(
            text(
                """
                select id
                  from batch_items
                 where batch_id = :batch_id and status = :pending
                 order by position asc
                 for update skip locked
                 limit 1
                """
            ),
            {"batch_id": batch_id, "pending": ITEM_STATUS_PENDING},
        ).first()
        if row is None:
            items = session.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.position).all()
            batch.status = _batch_final_status(items, cancel_requested=batch.cancel_requested)
            batch.finished_at = now
            batch.worker_id = None
            _recount_batch(session, batch_id)
            return None
        item = session.get(BatchItem, row.id)
        if item is None:
            return None
        item.status = ITEM_STATUS_RUNNING
        item.started_at = now
        batch.heartbeat_at = now
        return item.id


def complete_item_success(item_id: str, run_id: str, result_data: dict[str, Any]) -> None:
    with SessionLocal.begin() as session:
        item = session.get(BatchItem, item_id)
        if item is None:
            return
        item.status = ITEM_STATUS_SUCCESS
        item.run_id = run_id if run_id and session.get(DbRun, run_id) is not None else None
        item.result_data = result_data
        item.error_data = {}
        item.finished_at = utc_now()
        batch = session.get(DbBatch, item.batch_id)
        if batch is not None:
            batch.heartbeat_at = utc_now()
            _recount_batch(session, batch.id)


def complete_item_error(item_id: str, run_id: str | None, message: str, error_data: dict[str, Any] | None = None) -> None:
    with SessionLocal.begin() as session:
        item = session.get(BatchItem, item_id)
        if item is None:
            return
        item.status = ITEM_STATUS_ERROR
        item.run_id = run_id if run_id and session.get(DbRun, run_id) is not None else None
        payload = dict(error_data or {})
        payload.setdefault("message", str(message or "Erro na execucao do cliente.")[:1000])
        item.error_data = payload
        item.finished_at = utc_now()
        batch = session.get(DbBatch, item.batch_id)
        if batch is not None:
            batch.heartbeat_at = utc_now()
            _recount_batch(session, batch.id)


def cancel_pending_items(session: Any, batch_id: str) -> None:
    now = utc_now()
    (
        session.query(BatchItem)
        .filter(BatchItem.batch_id == batch_id, BatchItem.status == ITEM_STATUS_PENDING)
        .update({BatchItem.status: ITEM_STATUS_CANCELLED, BatchItem.finished_at: now}, synchronize_session=False)
    )


def finish_batch_if_done(batch_id: str) -> str | None:
    with SessionLocal.begin() as session:
        batch = session.get(DbBatch, batch_id)
        if batch is None:
            return None
        pending = session.query(BatchItem).filter(BatchItem.batch_id == batch_id, BatchItem.status == ITEM_STATUS_PENDING).count()
        running = session.query(BatchItem).filter(BatchItem.batch_id == batch_id, BatchItem.status == ITEM_STATUS_RUNNING).count()
        if pending or running:
            _recount_batch(session, batch_id)
            return batch.status
        items = session.query(BatchItem).filter(BatchItem.batch_id == batch_id).order_by(BatchItem.position).all()
        batch.status = _batch_final_status(items, cancel_requested=batch.cancel_requested)
        batch.finished_at = batch.finished_at or utc_now()
        batch.worker_id = None
        _recount_batch(session, batch_id)
        return batch.status


def mark_batch_interrupted(batch_id: str, reason: str, metadata: dict[str, Any] | None = None) -> None:
    with SessionLocal.begin() as session:
        batch = session.get(DbBatch, batch_id)
        if batch is None:
            return
        current = dict(batch.metadata_json or {})
        current["interrupted_reason"] = reason
        current["interrupted_at"] = utc_now_iso()
        if metadata:
            current["interrupted_metadata"] = metadata
        batch.metadata_json = current
        batch.status = BATCH_STATUS_INTERRUPTED
        batch.finished_at = utc_now()
        batch.worker_id = None


def recover_stale_batches(stale_seconds: int) -> int:
    threshold = utc_now() - timedelta(seconds=max(1, int(stale_seconds)))
    recovered = 0
    with SessionLocal.begin() as session:
        batches = (
            session.query(DbBatch)
            .filter(DbBatch.status.in_([BATCH_STATUS_RUNNING, BATCH_STATUS_CANCEL_REQUESTED]))
            .filter(DbBatch.heartbeat_at.is_not(None), DbBatch.heartbeat_at < threshold)
            .order_by(DbBatch.created_at)
            .all()
        )
        for batch in batches:
            running_items = (
                session.query(BatchItem)
                .filter(BatchItem.batch_id == batch.id, BatchItem.status == ITEM_STATUS_RUNNING)
                .order_by(BatchItem.position)
                .all()
            )
            for item in running_items:
                item.status = ITEM_STATUS_INTERRUPTED
                item.finished_at = utc_now()
                item.error_data = {
                    "message": "Item interrompido por recovery: worker/batch stale.",
                    "reason": "stale_running_item",
                    "previous_worker_id": batch.worker_id,
                    "last_heartbeat_at": batch.heartbeat_at.isoformat() if batch.heartbeat_at else None,
                    "recovered_at": utc_now_iso(),
                }
                recovered += 1
            pending_count = session.query(BatchItem).filter(BatchItem.batch_id == batch.id, BatchItem.status == ITEM_STATUS_PENDING).count()
            batch.worker_id = None
            batch.heartbeat_at = utc_now()
            if pending_count:
                batch.status = BATCH_STATUS_QUEUED
                batch.started_at = None
            else:
                items = session.query(BatchItem).filter(BatchItem.batch_id == batch.id).order_by(BatchItem.position).all()
                batch.status = _batch_final_status(items, cancel_requested=batch.cancel_requested)
                batch.finished_at = utc_now()
            _recount_batch(session, batch.id)
    return recovered


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
