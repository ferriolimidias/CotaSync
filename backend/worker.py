from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from backend.db import Batch as DbBatch, BatchItem, Run as DbRun, SessionLocal, WorkerInstance, engine
from backend.schemas.runs import ActionRunRequest
from backend.services.action_runner import missing_required_variables, run_action_sync
from backend.services.actions_repository import find_action
from backend.services.batch_runner import (
    BATCH_STATUS_CANCEL_REQUESTED,
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_INTERRUPTED,
    BATCH_STATUS_RUNNING,
    ITEM_STATUS_CANCELLED,
    ITEM_STATUS_PENDING,
    cancel_pending_items,
    claim_next_batch,
    claim_next_item,
    complete_item_error,
    complete_item_success,
    finish_batch_if_done,
    mark_batch_interrupted,
    recover_stale_batches,
    utc_now,
    utc_now_iso,
)

logger = logging.getLogger("cotasync.worker")

BROWSER_ADVISORY_LOCK_KEY = 76003001
DEFAULT_HEARTBEAT_SECONDS = 10
DEFAULT_STALE_SECONDS = 60
DEFAULT_POLL_SECONDS = 2


def heartbeat_seconds() -> int:
    return max(1, int(os.getenv("COTASYNC_WORKER_HEARTBEAT_SECONDS", str(DEFAULT_HEARTBEAT_SECONDS))))


def stale_seconds() -> int:
    return max(heartbeat_seconds() * 3, int(os.getenv("COTASYNC_WORKER_STALE_SECONDS", str(DEFAULT_STALE_SECONDS))))


def poll_seconds() -> float:
    return max(0.2, float(os.getenv("COTASYNC_WORKER_POLL_SECONDS", str(DEFAULT_POLL_SECONDS))))


def _status_payload(row: WorkerInstance | None) -> dict[str, Any]:
    if row is None:
        return {"online": False, "status": "offline"}
    stale_at = utc_now() - timedelta(seconds=stale_seconds())
    online = bool(row.heartbeat_at and row.heartbeat_at >= stale_at and row.status != "offline")
    return {
        "online": online,
        "instance_id": row.instance_id,
        "status": row.status if online else "offline",
        "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "stopped_at": row.stopped_at.isoformat() if row.stopped_at else None,
        "current_batch_id": row.current_batch_id,
        "current_batch_item_id": row.current_batch_item_id,
        "hostname": row.hostname,
        "browser_lock": False,
        "version": os.getenv("COTASYNC_VERSION") or os.getenv("GIT_COMMIT") or "",
    }


def latest_worker_status() -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.query(WorkerInstance).order_by(WorkerInstance.heartbeat_at.desc().nullslast()).first()
        payload = _status_payload(row)
    payload["browser_lock"] = browser_lock_available()
    return payload


def browser_lock_available() -> bool:
    try:
        with engine.connect() as conn:
            acquired = conn.execute(text("select pg_try_advisory_lock(:key)"), {"key": BROWSER_ADVISORY_LOCK_KEY}).scalar()
            if acquired:
                conn.execute(text("select pg_advisory_unlock(:key)"), {"key": BROWSER_ADVISORY_LOCK_KEY})
            return bool(acquired)
    except Exception:
        logger.exception("Falha ao consultar advisory lock do browser.")
        return False


class BrowserAdvisoryLock:
    def __init__(self) -> None:
        self._conn: Any | None = None

    def acquire(self) -> bool:
        self._conn = engine.connect()
        acquired = self._conn.execute(text("select pg_try_advisory_lock(:key)"), {"key": BROWSER_ADVISORY_LOCK_KEY}).scalar()
        if acquired:
            return True
        self.release()
        return False

    def release(self) -> None:
        if self._conn is None:
            return
        with suppress(Exception):
            self._conn.execute(text("select pg_advisory_unlock(:key)"), {"key": BROWSER_ADVISORY_LOCK_KEY})
        with suppress(Exception):
            self._conn.close()
        self._conn = None


class PersistentBatchWorker:
    def __init__(self, instance_id: str | None = None) -> None:
        self.instance_id = instance_id or f"{socket.gethostname()}-{uuid4()}"
        self.worker_row_id = self.instance_id
        self.hostname = socket.gethostname()
        self.stop_event = asyncio.Event()
        self.current_batch_id: str | None = None
        self.current_item_id: str | None = None
        self.heartbeat_task: asyncio.Task[None] | None = None

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, self.request_stop)

    def request_stop(self) -> None:
        logger.info("Worker %s recebeu shutdown gracioso.", self.instance_id)
        self.stop_event.set()

    def register(self) -> None:
        now = utc_now()
        with SessionLocal.begin() as session:
            row = session.get(WorkerInstance, self.worker_row_id)
            if row is None:
                row = WorkerInstance(
                    id=self.worker_row_id,
                    instance_id=self.instance_id,
                    status="starting",
                    started_at=now,
                    heartbeat_at=now,
                    hostname=self.hostname,
                    metadata_json={"heartbeat_seconds": heartbeat_seconds(), "stale_seconds": stale_seconds()},
                )
                session.add(row)
            else:
                row.status = "starting"
                row.started_at = now
                row.heartbeat_at = now
                row.stopped_at = None
                row.hostname = self.hostname
                row.metadata_json = {"heartbeat_seconds": heartbeat_seconds(), "stale_seconds": stale_seconds()}

    def heartbeat(self, status: str) -> None:
        with SessionLocal.begin() as session:
            row = session.get(WorkerInstance, self.worker_row_id)
            if row is None:
                return
            row.status = status
            row.heartbeat_at = utc_now()
            row.current_batch_id = self.current_batch_id
            row.current_batch_item_id = self.current_item_id
            if self.current_batch_id:
                batch = session.get(DbBatch, self.current_batch_id)
                if batch is not None and batch.status in {BATCH_STATUS_RUNNING, BATCH_STATUS_CANCEL_REQUESTED}:
                    batch.heartbeat_at = utc_now()

    async def heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            self.heartbeat("running" if self.current_batch_id else "idle")
            await asyncio.sleep(heartbeat_seconds())

    def startup_recovery(self) -> None:
        now = utc_now()
        threshold = now - timedelta(seconds=stale_seconds())
        with SessionLocal.begin() as session:
            stale_workers = (
                session.query(WorkerInstance)
                .filter(WorkerInstance.status.in_(["starting", "idle", "running", "stopping"]))
                .filter(WorkerInstance.heartbeat_at.is_not(None), WorkerInstance.heartbeat_at < threshold)
                .all()
            )
            for worker in stale_workers:
                worker.status = "offline"
                worker.stopped_at = now
        recovered = recover_stale_batches(stale_seconds())
        logger.info("Startup recovery concluido worker=%s stale_items=%s", self.instance_id, recovered)

    async def run(self) -> None:
        self.install_signal_handlers()
        self.register()
        self.startup_recovery()
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        try:
            while not self.stop_event.is_set():
                self.heartbeat("idle")
                batch_id = claim_next_batch(self.instance_id)
                if not batch_id:
                    await asyncio.sleep(poll_seconds())
                    continue
                await self.execute_batch(batch_id)
        finally:
            if self.heartbeat_task is not None:
                self.heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.heartbeat_task
            with SessionLocal.begin() as session:
                row = session.get(WorkerInstance, self.worker_row_id)
                if row is not None:
                    row.status = "offline"
                    row.stopped_at = utc_now()
                    row.heartbeat_at = utc_now()
                    row.current_batch_id = None
                    row.current_batch_item_id = None

    async def execute_batch(self, batch_id: str) -> None:
        lock = BrowserAdvisoryLock()
        if not lock.acquire():
            logger.warning("Browser advisory lock ocupado; batch %s volta para fila.", batch_id)
            with SessionLocal.begin() as session:
                batch = session.get(DbBatch, batch_id)
                if batch is not None and batch.status == BATCH_STATUS_RUNNING:
                    batch.status = "queued"
                    batch.worker_id = None
            return
        self.current_batch_id = batch_id
        self.current_item_id = None
        self.heartbeat("running")
        try:
            while not self.stop_event.is_set():
                item_id = claim_next_item(batch_id)
                if item_id is None:
                    finish_batch_if_done(batch_id)
                    return
                self.current_item_id = item_id
                self.heartbeat("running")
                systemic_reason = await self.execute_item(batch_id, item_id)
                self.current_item_id = None
                if systemic_reason:
                    mark_batch_interrupted(batch_id, systemic_reason)
                    return
                status = finish_batch_if_done(batch_id)
                if status not in {BATCH_STATUS_RUNNING, BATCH_STATUS_CANCEL_REQUESTED}:
                    return
                delay = self._delay_seconds(batch_id)
                if delay > 0 and self._has_pending_item(batch_id):
                    await asyncio.sleep(delay)
        finally:
            lock.release()
            self.current_batch_id = None
            self.current_item_id = None
            self.heartbeat("idle")

    async def execute_item(self, batch_id: str, item_id: str) -> str | None:
        with SessionLocal() as session:
            item = session.get(BatchItem, item_id)
            batch = session.get(DbBatch, batch_id)
            if item is None or batch is None:
                return "structural_inconsistency"
            action_id = batch.action_id or ""
            variables = dict(item.input_variables or {})
            client_id = item.client_id
        action = find_action(action_id)
        if action is None:
            complete_item_error(item_id, None, "Acao nao encontrada para executar o batch.", {"reason": "action_not_found"})
            return None
        try:
            missing = missing_required_variables(action, variables)
            if missing:
                raise ValueError("Variaveis obrigatorias ausentes: " + ", ".join(missing))
            run = await run_action_sync(
                action,
                ActionRunRequest(variables=variables, mode="sync", requested_by="worker", run_origin="operational"),
            )
            with SessionLocal.begin() as session:
                db_run = session.get(DbRun, run.id)
                if db_run is not None:
                    db_run.batch_id = batch_id
                    db_run.client_id = client_id
            payload = run.result_payload if isinstance(run.result_payload, dict) else {}
            if run.status == "success":
                complete_item_success(item_id, run.id, payload)
                return None
            complete_item_error(item_id, run.id, run.error_message or "Falha na execucao do cliente.", payload)
            return self._systemic_reason(payload)
        except Exception as exc:
            message = str(exc)[:1000] or type(exc).__name__
            complete_item_error(item_id, None, message, {"message": message, "exception_type": type(exc).__name__})
            return None

    @staticmethod
    def _systemic_reason(payload: dict[str, Any]) -> str | None:
        reason = str(payload.get("reason") or payload.get("session_state") or "").lower()
        operator_action = bool(payload.get("operator_action_required"))
        if operator_action and any(part in reason for part in ("session", "login", "expired", "expir")):
            return "external_session_expired"
        if any(part in reason for part in ("external_session_expired", "sessao expirada", "session expired")):
            return "external_session_expired"
        browser_mode = str(payload.get("browser_mode") or "").lower()
        exception_type = str(payload.get("exception_type") or "").lower()
        if browser_mode == "desktop_browser" and any(part in exception_type for part in ("connection", "playwright", "targetclosed")):
            return "browser_unavailable"
        return None

    @staticmethod
    def _delay_seconds(batch_id: str) -> float:
        with SessionLocal() as session:
            batch = session.get(DbBatch, batch_id)
            return max(0.0, float(batch.delay_seconds if batch is not None else 0))

    @staticmethod
    def _has_pending_item(batch_id: str) -> bool:
        with SessionLocal() as session:
            batch = session.get(DbBatch, batch_id)
            if batch is not None and (batch.cancel_requested or batch.status == BATCH_STATUS_CANCEL_REQUESTED):
                with SessionLocal.begin() as write_session:
                    write_batch = write_session.get(DbBatch, batch_id)
                    if write_batch is not None:
                        cancel_pending_items(write_session, batch_id)
                        write_batch.status = BATCH_STATUS_CANCELLED
                        write_batch.finished_at = utc_now()
                return False
            return bool(
                session.query(BatchItem)
                .filter(BatchItem.batch_id == batch_id, BatchItem.status == ITEM_STATUS_PENDING)
                .count()
            )


async def amain() -> None:
    logging.basicConfig(level=os.getenv("COTASYNC_LOG_LEVEL", "INFO"))
    worker = PersistentBatchWorker(os.getenv("COTASYNC_WORKER_INSTANCE_ID"))
    await worker.run()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
