"""Durable orchestration for a new external-access logical unit."""

from __future__ import annotations

import logging
import asyncio
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from playwright.async_api import async_playwright

from backend.db import AccessCycle, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_coordinator import AccessCycleError, start_canonical_access
from backend.services.access_profiles import active_access_profile_public
from backend.services.browser_providers import BrowserIdentitySession, browser_provider, desktop_cdp_url

logger = logging.getLogger("cotasync.access_cycles")

_WORKER_ACCESS_EXECUTOR: ContextVar[Any | None] = ContextVar("worker_access_executor", default=None)


def bind_worker_access_executor(executor: Any) -> Any:
    return _WORKER_ACCESS_EXECUTOR.set(executor)


def reset_worker_access_executor(token: Any) -> None:
    _WORKER_ACCESS_EXECUTOR.reset(token)


def _safe_url(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _event_payload(stage: str, event: str, status: str, context: dict[str, Any]) -> dict[str, Any]:
    safe = dict(context)
    for key in ("entry_url", "url", "current_url"):
        if key in safe:
            safe[key] = _safe_url(safe[key])
    for key in ("token", "cookie", "password", "secret"):
        safe.pop(key, None)
    return {"timestamp": datetime.now(UTC).isoformat(), "stage": stage, "event": event, "status": status, **safe}


def _append_event(cycle_id: str, stage: str, event: str, status: str, **context: Any) -> None:
    with SessionLocal.begin() as db:
        cycle = db.get(AccessCycle, cycle_id)
        if cycle is None:
            return
        cycle.events = [*(cycle.events or []), _event_payload(stage, event, status, context)][-500:]
        cycle.stage = stage
        cycle.heartbeat_at = datetime.now(UTC)
        if status == "waiting":
            cycle.status = "waiting"
        elif status in {"started", "observed", "retrying"} and cycle.status == "starting":
            cycle.status = "running"


def create_access_cycle(external_system_id: str, access_profile_id: str) -> dict[str, Any]:
    with SessionLocal.begin() as db:
        system = db.get(ExternalSystem, str(external_system_id))
        profile = db.get(ExternalAccessProfile, str(access_profile_id))
        if system is None or profile is None or not profile.active:
            raise ValueError("Sistema externo ou perfil de acesso inválido.")
        if profile.external_system_id != system.id:
            raise ValueError("O perfil de acesso não pertence ao sistema externo.")
        entry_url = str((system.config or {}).get("entry_url") or "").strip()
        if not entry_url:
            raise ValueError("O sistema externo não possui entry_url configurado.")
        cycle = AccessCycle(
            id=str(uuid4()), external_system_id=system.id, access_profile_id=profile.id,
            entry_url=entry_url,
            status="starting", stage="access_start", events=[], heartbeat_at=datetime.now(UTC),
        )
        db.add(cycle)
        cycle_id = cycle.id
    _append_event(cycle_id, "access", "ACCESS_CYCLE_CREATED", "success", access_profile_id=access_profile_id, external_system_id=external_system_id, canonical_entry_url_source="ExternalSystem.entry_url", entry_url=entry_url)
    return {"access_cycle_id": cycle_id, "status": "starting", "access_profile_id": access_profile_id}


def get_access_cycle(cycle_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        cycle = db.get(AccessCycle, str(cycle_id))
        if cycle is None:
            return None
        return {
            "access_cycle_id": cycle.id, "external_system_id": cycle.external_system_id,
            "access_profile_id": cycle.access_profile_id, "status": cycle.status,
            "entry_url": _safe_url(cycle.entry_url),
            "stage": cycle.stage, "error_code": cycle.error_code, "error_message": cycle.error_message,
            "events": cycle.events or [],
            "created_at": cycle.created_at.isoformat() if cycle.created_at else None,
            "started_at": cycle.started_at.isoformat() if cycle.started_at else None,
            "heartbeat_at": cycle.heartbeat_at.isoformat() if cycle.heartbeat_at else None,
            "finished_at": cycle.finished_at.isoformat() if cycle.finished_at else None,
        }


async def start_persisted_access_cycle(
    external_system_id: str,
    access_profile_id: str,
    *,
    cancellation_probe: Any | None = None,
) -> dict[str, Any]:
    """Create a durable cycle and wait for the worker-owned coordinator."""
    cycle = create_access_cycle(external_system_id, access_profile_id)
    cycle_id = str(cycle["access_cycle_id"])
    executor = _WORKER_ACCESS_EXECUTOR.get()
    if executor is not None:
        await executor(cycle_id)
    while True:
        if cancellation_probe is not None and await cancellation_probe():
            raise AccessCycleError("Ciclo de acesso cancelado.", code="access_cycle_cancelled", stage="access")
        current = get_access_cycle(cycle_id)
        if current is None:
            raise AccessCycleError("Ciclo de acesso não encontrado.", code="access_cycle_missing", stage="access")
        if current.get("status") == "ready" and current.get("stage") == "external_system_ready":
            return current
        if current.get("status") in {"failed", "cancelled", "superseded"}:
            raise AccessCycleError(
                str(current.get("error_message") or "O ciclo de acesso não foi concluído."),
                code=str(current.get("error_code") or "access_cycle_failed"),
                stage=str(current.get("stage") or "access"),
            )
        await asyncio.sleep(0.5)


def claim_next_access_cycle(worker_id: str | None = None) -> str | None:
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.status == "starting").order_by(AccessCycle.created_at).with_for_update(skip_locked=True))
        if cycle is None:
            return None
        cycle.status = "running"
        cycle.worker_id = worker_id
        cycle.started_at = datetime.now(UTC)
        cycle.heartbeat_at = datetime.now(UTC)
        cycle_id = cycle.id
    _append_event(cycle_id, "access", "ACCESS_CYCLE_STARTED", "started")
    return cycle_id


def recover_stale_access_cycles(stale_before: datetime) -> int:
    """Return abandoned cycles to the pending state without touching active waits."""
    recovered = 0
    with SessionLocal.begin() as db:
        cycles = (
            db.query(AccessCycle)
            .filter(AccessCycle.status.in_(["running", "waiting"]))
            .filter(AccessCycle.worker_id.is_not(None))
            .filter(AccessCycle.heartbeat_at.is_not(None), AccessCycle.heartbeat_at < stale_before)
            .with_for_update(skip_locked=True)
            .all()
        )
        for cycle in cycles:
            cycle.status = "starting"
            cycle.stage = "access_start"
            cycle.started_at = None
            cycle.heartbeat_at = datetime.now(UTC)
            cycle.worker_id = None
            recovered += 1
    return recovered


def touch_access_cycle(cycle_id: str, *, status: str | None = None) -> None:
    with SessionLocal.begin() as db:
        cycle = db.get(AccessCycle, cycle_id)
        if cycle is not None:
            cycle.heartbeat_at = datetime.now(UTC)
            if status:
                cycle.status = status


def finish_access_cycle(cycle_id: str, *, status: str, error_code: str | None = None, error_message: str | None = None) -> None:
    with SessionLocal.begin() as db:
        cycle = db.get(AccessCycle, cycle_id)
        if cycle is None:
            return
        cycle.status = status
        cycle.error_code = error_code
        cycle.error_message = error_message
        if status == "ready":
            cycle.stage = "external_system_ready"
        cycle.finished_at = datetime.now(UTC)
        cycle.heartbeat_at = datetime.now(UTC)


async def execute_access_cycle(cycle_id: str) -> None:
    with SessionLocal() as db:
        cycle = db.get(AccessCycle, cycle_id)
        if cycle is None:
            return
        system = db.get(ExternalSystem, cycle.external_system_id)
        profile = db.get(ExternalAccessProfile, cycle.access_profile_id)
        config = dict(system.config or {}) if system else {}
        profile_data = active_access_profile_public(cycle.access_profile_id) if profile else None
    if system is None or profile is None or profile_data is None:
        finish_access_cycle(cycle_id, status="failed", error_code="access_context_invalid", error_message="Contexto de acesso não encontrado.")
        return
    playwright = await async_playwright().start()
    try:
        connection = await browser_provider("desktop_browser").connect(playwright, f"access-cycle-{cycle_id}")
        identity_session = BrowserIdentitySession(connection.context, profile.id, scope=desktop_cdp_url())
        await identity_session.activate()
        timeline = lambda stage, event, status, **context: _append_event(cycle_id, stage, event, status, **context)
        await ensure_access_cycle(
            connection.page,
            external_system={
                "id": system.id,
                "entry_url": cycle.entry_url,
                "expected_system_host": str(config.get("expected_system_host") or ""),
                "identity_selector": str(config.get("identity_selector") or ""),
                "run_start_strategy": str(config.get("run_start_strategy") or "external_entry_each_run"),
            },
            access_profile=profile_data,
            action={"access_bootstrap": config.get("access_bootstrap") or []},
            timeline=timeline,
            require_external_system=True,
        )
        finish_access_cycle(cycle_id, status="ready")
    except AccessCycleError as exc:
        logger.warning("Ciclo de acesso %s terminou: %s", cycle_id, exc.code)
        finish_access_cycle(cycle_id, status="failed", error_code=exc.code, error_message=str(exc))
    except Exception:
        logger.exception("Falha no ciclo de acesso %s", cycle_id)
        finish_access_cycle(cycle_id, status="failed", error_code="access_cycle_failed", error_message="Falha operacional no ciclo de acesso.")
    finally:
        await playwright.stop()


async def ensure_access_cycle(*args: Any, **kwargs: Any):
    """Single in-process entry point for learning and execution boundaries."""
    return await start_canonical_access(*args, **kwargs)
