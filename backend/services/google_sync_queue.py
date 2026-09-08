"""Durable outbound queue for Google Sheets changes.

Collection and external synchronization are intentionally separate operations.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from backend.db import GoogleSyncPending, SessionLocal, SpreadsheetConnector


# ``syncing`` is included so a worker/process interruption cannot strand a
# change permanently outside the retry queue.
PENDING_STATUSES = {"pending", "error", "syncing"}


def enqueue_pending_change(
    db: Any,
    *,
    spreadsheet_id: str,
    client_id: str,
    field_id: str,
    value: str,
    batch_id: str | None = None,
    run_id: str | None = None,
) -> None:
    connectors = list(db.scalars(select(SpreadsheetConnector).where(
        SpreadsheetConnector.spreadsheet_id == spreadsheet_id,
        SpreadsheetConnector.connector_type == "google_sheets",
    )))
    for connector in connectors:
        row = db.scalar(select(GoogleSyncPending).where(
            GoogleSyncPending.connector_id == connector.id,
            GoogleSyncPending.client_id == client_id,
            GoogleSyncPending.field_id == field_id,
        ))
        if row is None:
            row = GoogleSyncPending(
                id=str(uuid4()),
                connector_id=connector.id,
                spreadsheet_id=spreadsheet_id,
                client_id=client_id,
                field_id=field_id,
            )
            db.add(row)
        row.value = str(value)
        row.batch_id = batch_id
        row.run_id = run_id
        row.status = "pending"
        row.last_error = None
        row.synced_at = None


def pending_count(*, spreadsheet_id: str | None = None) -> int:
    with SessionLocal() as db:
        query = select(GoogleSyncPending).where(GoogleSyncPending.status.in_(PENDING_STATUSES))
        if spreadsheet_id:
            query = query.where(GoogleSyncPending.spreadsheet_id == spreadsheet_id)
        return len(list(db.scalars(query)))


def send_pending_google(*, spreadsheet_id: str | None = None, tenant_id: str = "default") -> dict[str, Any]:
    """Send current internal sheet state once per connector with pending rows.

    The connector implementation performs one grouped sheet write. No browser,
    action runner, or AI provider is called here.
    """
    from backend.services.system_spreadsheets import SystemSpreadsheetError, sync_google_pending

    with SessionLocal() as db:
        query = select(GoogleSyncPending).where(GoogleSyncPending.status.in_(PENDING_STATUSES))
        if spreadsheet_id:
            query = query.where(GoogleSyncPending.spreadsheet_id == spreadsheet_id)
        rows = list(db.scalars(query))
    connector_ids = sorted({str(row.connector_id) for row in rows if row.connector_id})
    synced = 0
    failed = 0
    errors: list[dict[str, str]] = []
    for connector_id in connector_ids:
        connector_rows = [row for row in rows if row.connector_id == connector_id]
        sheet_id = connector_rows[0].spreadsheet_id
        with SessionLocal.begin() as db:
            db.query(GoogleSyncPending).filter(GoogleSyncPending.id.in_([row.id for row in connector_rows])).update(
                {GoogleSyncPending.status: "syncing", GoogleSyncPending.attempts: GoogleSyncPending.attempts + 1},
                synchronize_session=False,
            )
        try:
            sync_google_pending(
                sheet_id,
                [
                    {
                        "client_id": row.client_id,
                        "field_id": row.field_id,
                        "value": row.value,
                    }
                    for row in connector_rows
                ],
                tenant_id=tenant_id,
            )
        except SystemSpreadsheetError as exc:
            message = str(exc)[:500]
            with SessionLocal.begin() as db:
                db.query(GoogleSyncPending).filter(GoogleSyncPending.id.in_([row.id for row in connector_rows])).update(
                    {GoogleSyncPending.status: "error", GoogleSyncPending.last_error: message},
                    synchronize_session=False,
                )
            failed += len(connector_rows)
            errors.append({"spreadsheet_id": sheet_id, "message": message})
            continue
        now = datetime.now(UTC)
        with SessionLocal.begin() as db:
            db.query(GoogleSyncPending).filter(GoogleSyncPending.id.in_([row.id for row in connector_rows])).update(
                {GoogleSyncPending.status: "synced", GoogleSyncPending.last_error: None, GoogleSyncPending.synced_at: now},
                synchronize_session=False,
            )
        synced += len(connector_rows)
    return {"pending_before": len(rows), "synced": synced, "failed": failed, "errors": errors}
