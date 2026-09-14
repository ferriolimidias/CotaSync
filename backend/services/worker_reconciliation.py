"""Small, isolated reconciliation operations for worker metadata."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_

from backend.db import AccessCycle, Batch, Run, SessionLocal, WorkerInstance


STALE_WORKER_RECONCILIATION_REASON = "STALE_WORKER_RECONCILIATION"
ACTIVE_BATCH_STATUSES = {"queued", "running", "cancel_requested", "pending"}
TERMINAL_RUN_STATUSES = {"success", "completed", "failed", "error", "cancelled", "interrupted", "superseded"}


class StaleWorkerReconciliationDenied(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _stale_seconds() -> int:
    heartbeat = max(1, int(os.getenv("COTASYNC_WORKER_HEARTBEAT_SECONDS", "10")))
    return max(heartbeat * 3, int(os.getenv("COTASYNC_WORKER_STALE_SECONDS", "60")))


def _is_stale(heartbeat_at: datetime | None, *, now: datetime) -> bool:
    return bool(heartbeat_at and heartbeat_at < now - timedelta(seconds=_stale_seconds()))


def reconcile_stale_worker_instance(
    worker_id: str,
    *,
    process_absent_confirmed: bool,
    actor: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Clear only an orphan worker row; never recover or claim operational work."""
    if not process_absent_confirmed:
        raise StaleWorkerReconciliationDenied(
            "PROCESS_ABSENCE_CONFIRMATION_REQUIRED",
            "A ausência do processo real precisa ser confirmada explicitamente.",
        )

    observed_at = now or datetime.now(UTC)
    with SessionLocal.begin() as session:
        worker = (
            session.query(WorkerInstance)
            .filter(or_(WorkerInstance.id == worker_id, WorkerInstance.instance_id == worker_id))
            .with_for_update()
            .one_or_none()
        )
        if worker is None:
            raise StaleWorkerReconciliationDenied("WORKER_NOT_FOUND", "WorkerInstance não encontrado.")

        previous_status = worker.status
        refs = {
            "current_batch_id": worker.current_batch_id,
            "current_batch_item_id": worker.current_batch_item_id,
        }
        if previous_status == "offline" and not any(refs.values()):
            return {
                "worker_id": worker.id,
                "previous_status": previous_status,
                "new_status": "offline",
                "stale_detected": True,
                "ownership_clear": True,
                "current_refs_cleared": False,
                "reason": STALE_WORKER_RECONCILIATION_REASON,
                "idempotent": True,
            }
        if previous_status == "offline":
            stale_detected = True
        else:
            stale_detected = _is_stale(worker.heartbeat_at, now=observed_at)
            if not stale_detected:
                raise StaleWorkerReconciliationDenied(
                    "WORKER_NOT_STALE",
                    "O WorkerInstance ainda possui heartbeat fresco ou estado não confirmável.",
                )

        worker_keys = {worker.id, worker.instance_id}
        active_batch = (
            session.query(Batch)
            .filter(Batch.worker_id.in_(worker_keys), Batch.status.in_(ACTIVE_BATCH_STATUSES))
            .with_for_update()
            .first()
        )
        if active_batch is not None:
            raise StaleWorkerReconciliationDenied(
                "ACTIVE_BATCH_OWNER",
                "O worker ainda está associado a um batch operacional.",
                active_batch_id=active_batch.id,
            )

        fresh_cycle = (
            session.query(AccessCycle)
            .filter(AccessCycle.worker_id.in_(worker_keys))
            .filter(AccessCycle.status.not_in({"ready", "failed", "cancelled", "superseded"}))
            .filter(AccessCycle.heartbeat_at.is_not(None), AccessCycle.heartbeat_at >= observed_at - timedelta(seconds=_stale_seconds()))
            .with_for_update()
            .first()
        )
        if fresh_cycle is not None:
            raise StaleWorkerReconciliationDenied(
                "ACTIVE_ACCESS_OWNER",
                "O worker ainda possui um AccessCycle ativo com heartbeat fresco.",
                access_cycle_id=fresh_cycle.id,
            )

        active_run = (
            session.query(Run)
            .filter(Run.runner.in_(worker_keys), Run.status.not_in(TERMINAL_RUN_STATUSES))
            .with_for_update()
            .first()
        )
        if active_run is not None:
            raise StaleWorkerReconciliationDenied(
                "ACTIVE_RUN_OWNER",
                "O worker ainda possui uma Run ativa associada.",
                run_id=active_run.id,
            )

        previous_metadata = dict(worker.metadata_json or {})
        audit = {
            "operation": STALE_WORKER_RECONCILIATION_REASON,
            "at": observed_at.isoformat(),
            "actor": str(actor or "operator").strip()[:255],
            "previous_status": previous_status,
            "new_status": "offline",
            "stale_detected": stale_detected,
            "ownership_clear": True,
            "cleared_refs": {key: value for key, value in refs.items() if value},
        }
        history = list(previous_metadata.get("worker_reconciliation_audit") or [])
        history.append(audit)
        worker.metadata_json = {**previous_metadata, "worker_reconciliation_audit": history[-100:]}
        worker.status = "offline"
        worker.stopped_at = observed_at
        worker.current_batch_id = None
        worker.current_batch_item_id = None

        return {
            "worker_id": worker.id,
            "previous_status": previous_status,
            "new_status": worker.status,
            "stale_detected": stale_detected,
            "ownership_clear": True,
            "current_refs_cleared": any(refs.values()),
            "reason": STALE_WORKER_RECONCILIATION_REASON,
            "idempotent": False,
        }
