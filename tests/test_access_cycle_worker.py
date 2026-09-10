from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from backend.db import AccessCycle, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_cycles import claim_next_access_cycle, recover_stale_access_cycles
from backend.worker import PersistentBatchWorker


def test_auto_consume_calls_access_cycle_executor():
    worker = PersistentBatchWorker("access-cycle-test")
    worker.execute_access_cycle = AsyncMock()  # type: ignore[method-assign]
    with patch("backend.worker.claim_next_access_cycle", return_value="cycle-a"):
        assert asyncio.run(worker.poll_access_cycle_once()) is True
    worker.execute_access_cycle.assert_awaited_once_with("cycle-a")


def test_empty_access_cycle_queue_does_not_execute_browser_work():
    worker = PersistentBatchWorker("access-cycle-empty-test")
    worker.execute_access_cycle = AsyncMock()  # type: ignore[method-assign]
    with patch("backend.worker.claim_next_access_cycle", return_value=None):
        assert asyncio.run(worker.poll_access_cycle_once()) is False
    worker.execute_access_cycle.assert_not_awaited()


def _cycle(status: str = "starting", heartbeat_at: datetime | None = None, worker_id: str | None = None) -> tuple[str, str, str]:
    system_id, profile_id, cycle_id = (str(uuid4()) for _ in range(3))
    with SessionLocal.begin() as db:
        db.add(ExternalSystem(id=system_id, name=f"cycle-test-{system_id}", config={"entry_url": "https://entry.example.test"}))
        db.flush()
        db.add(ExternalAccessProfile(id=profile_id, tenant_id="default", external_system_id=system_id, display_name="Cycle test", login_identifier=f"{profile_id}@example.test", active=True))
        db.flush()
        db.add(AccessCycle(id=cycle_id, external_system_id=system_id, access_profile_id=profile_id, entry_url="https://entry.example.test", status=status, stage="access_start", events=[], heartbeat_at=heartbeat_at or datetime.now(UTC), worker_id=worker_id))
    return system_id, profile_id, cycle_id


def _remove_cycle(ids: tuple[str, str, str]) -> None:
    system_id, profile_id, cycle_id = ids
    with SessionLocal.begin() as db:
        cycle = db.get(AccessCycle, cycle_id)
        profile = db.get(ExternalAccessProfile, profile_id)
        system = db.get(ExternalSystem, system_id)
        if cycle:
            db.delete(cycle)
        if profile:
            db.delete(profile)
        if system:
            db.delete(system)


def test_double_claim_only_one_consumer_wins():
    ids = _cycle()
    try:
        assert claim_next_access_cycle("worker-a") == ids[2]
        assert claim_next_access_cycle("worker-b") is None
    finally:
        _remove_cycle(ids)


def test_active_heartbeat_is_not_recovered():
    ids = _cycle(status="waiting", worker_id="active-worker")
    try:
        assert recover_stale_access_cycles(datetime.now(UTC) - timedelta(seconds=60)) == 0
    finally:
        _remove_cycle(ids)


def test_stale_cycle_is_returned_to_pending_for_recovery():
    ids = _cycle(status="running", heartbeat_at=datetime.now(UTC) - timedelta(minutes=10), worker_id="dead-worker")
    try:
        assert recover_stale_access_cycles(datetime.now(UTC) - timedelta(seconds=60)) == 1
        assert claim_next_access_cycle("worker-recovery") == ids[2]
    finally:
        _remove_cycle(ids)


def test_first_coordinator_event_is_canonical_entry_navigation():
    ids = _cycle()

    class _Playwright:
        stop = AsyncMock()

    class _Provider:
        connect = AsyncMock(return_value=type("Connection", (), {"page": object()})())

    async def coordinator(*_args, **kwargs):
        kwargs["timeline"]("external_entry", "CANONICAL_ENTRY_NAVIGATION_STARTED", "started", entry_url="https://entry.example.test")

    async def start_playwright():
        return _Playwright()

    class _PlaywrightFactory:
        start = AsyncMock(side_effect=start_playwright)

    try:
        with patch("backend.services.access_cycles.async_playwright", return_value=_PlaywrightFactory()), patch("backend.services.access_cycles.browser_provider", return_value=_Provider()), patch("backend.services.access_cycles.ensure_access_cycle", side_effect=coordinator):
            from backend.services.access_cycles import execute_access_cycle
            asyncio.run(execute_access_cycle(ids[2]))
        with SessionLocal() as db:
            events = [item["event"] for item in (db.get(AccessCycle, ids[2]).events or [])]
        assert events[0] == "CANONICAL_ENTRY_NAVIGATION_STARTED"
    finally:
        _remove_cycle(ids)
