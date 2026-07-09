from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.services.batch_runner import (
    BatchRunnerError,
    batch_results_csv,
    cancel_batch,
    create_batch,
    list_batches,
    load_batch,
)

router = APIRouter(prefix="/api/batches", tags=["batches"])


class BatchCreateRequest(BaseModel):
    action_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    client_group: str | None = None
    client_ids: list[str] = Field(default_factory=list)
    requested_by: str = "api"
    delay_between_rows_seconds: float = 3


@router.post("")
async def create_batch_endpoint(payload: BatchCreateRequest) -> dict[str, Any]:
    try:
        batch = create_batch(
            action_id=payload.action_id,
            rows=payload.rows,
            client_group=payload.client_group,
            client_ids=payload.client_ids,
            requested_by=payload.requested_by,
            delay_between_rows_seconds=payload.delay_between_rows_seconds,
            auto_start=True,
        )
    except BatchRunnerError as exc:
        message = str(exc)
        status_code = 409 if "Ja existe um lote" in message else 422
        raise HTTPException(status_code=status_code, detail=message) from exc
    return {"status": "ok", "batch": batch}


@router.get("")
async def list_batches_endpoint(limit: int = 20) -> dict[str, Any]:
    batches = list_batches(limit=limit)
    return {"status": "ok", "count": len(batches), "batches": batches}


@router.get("/{batch_id}")
async def get_batch_endpoint(batch_id: str) -> dict[str, Any]:
    try:
        batch = load_batch(batch_id)
    except BatchRunnerError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch nao encontrado.")
    return {"status": "ok", "batch": batch}


@router.get("/{batch_id}/results.csv")
async def get_batch_results_csv_endpoint(batch_id: str) -> Response:
    try:
        batch = load_batch(batch_id)
    except BatchRunnerError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch nao encontrado.")
    csv_text = batch_results_csv(batch)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="batch_{batch_id}_results.csv"'},
    )


@router.post("/{batch_id}/cancel")
async def cancel_batch_endpoint(batch_id: str) -> dict[str, Any]:
    try:
        batch = cancel_batch(batch_id)
    except BatchRunnerError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "batch": batch}
