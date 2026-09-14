from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db import AccessCycle, ExternalAccessProfile, ExternalSystem
from backend.services.access_coordinator import CanonicalAccessCoordinator
from backend.services.access_cycles import (
    AccessCycleError,
    _coordinate_owned_access,
    bind_access_cycle_owner,
    finish_access_cycle,
    recover_stale_access_cycles,
    request_access_attention,
    request_access_resume,
    touch_access_cycle,
)


@pytest.fixture(autouse=True)
def isolated_queue(monkeypatch):
    from backend.db import engine
    from backend.services import access_cycles
    import backend.worker as worker_module

    with engine.connect() as connection:
        transaction = connection.begin()
        factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        monkeypatch.setattr(access_cycles, "SessionLocal", factory)
        monkeypatch.setattr(worker_module, "SessionLocal", factory)
        with factory.begin() as session:
            session.query(AccessCycle).delete()
        try:
            yield
        finally:
            transaction.rollback()


def _cycle(*, status: str = "running", worker_id: str | None = "worker-q") -> tuple[str, str, str]:
    suffix = uuid4().hex
    system_id, profile_id, cycle_id = f"q-system-{suffix}", f"q-profile-{suffix}", f"q-cycle-{suffix}"
    from backend.services import access_cycles

    with access_cycles.SessionLocal.begin() as db:
        db.add(ExternalSystem(id=system_id, name=system_id, config={"entry_url": "https://entry.example.test", "expected_system_host": "system.example.test"}))
        db.flush()
        db.add(ExternalAccessProfile(id=profile_id, tenant_id="default", external_system_id=system_id, display_name="Access test", login_identifier=f"{profile_id}@example.test", active=True))
        db.flush()
        db.add(AccessCycle(id=cycle_id, external_system_id=system_id, access_profile_id=profile_id, entry_url="https://entry.example.test", status=status, stage="access", worker_id=worker_id, browser_target_id="target-q", browser_context_id="context-q", events=[], heartbeat_at=datetime.now(UTC)))
    return system_id, profile_id, cycle_id


def _remove(ids: tuple[str, str, str]) -> None:
    from backend.services import access_cycles

    with access_cycles.SessionLocal.begin() as db:
        for model, item_id in ((AccessCycle, ids[2]), (ExternalAccessProfile, ids[1]), (ExternalSystem, ids[0])):
            row = db.get(model, item_id)
            if row is not None:
                db.delete(row)


def _status(cycle_id: str) -> str:
    from backend.services import access_cycles

    with access_cycles.SessionLocal() as db:
        return str(db.get(AccessCycle, cycle_id).status)


def test_worker_owned_attention_preserves_same_cycle_and_stops_coordinator():
    ids = _cycle()

    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        context = SimpleNamespace()
        identity = SimpleNamespace(access_profile_id=ids[1], context=context, persist=AsyncMock())

        async def coordinator(reobserve_current_page: bool = False):
            assert reobserve_current_page is False
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(_coordinate_owned_access(ids[2], identity, SimpleNamespace(context=context), coordinator_factory=coordinator))
        await started.wait()
        request_access_attention(ids[2], reason="operator_requested")
        await asyncio.sleep(0.4)
        assert _status(ids[2]) == "needs_attention"
        assert cancelled.is_set()
        touch_access_cycle(ids[2], status="running")
        assert _status(ids[2]) == "needs_attention"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        _remove(ids)


def test_picker_selection_stall_requests_worker_owned_attention():
    ids = _cycle()

    async def scenario() -> None:
        identity = SimpleNamespace(access_profile_id=ids[1], context=SimpleNamespace(), persist=AsyncMock())

        async def coordinator(reobserve_current_page: bool = False):
            assert reobserve_current_page is False
            raise AccessCycleError(
                "picker did not transition",
                code="ACCOUNT_SELECTION_STALLED",
                stage="account_picker",
            )

        task = asyncio.create_task(
            _coordinate_owned_access(
                ids[2],
                identity,
                SimpleNamespace(context=identity.context),
                coordinator_factory=coordinator,
            )
        )
        for _ in range(20):
            if _status(ids[2]) == "needs_attention":
                break
            await asyncio.sleep(0.05)
        assert _status(ids[2]) == "needs_attention"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        _remove(ids)


def test_resume_preserves_cycle_and_reobserves_without_entry_navigation():
    ids = _cycle()

    async def scenario() -> None:
        started = asyncio.Event()
        resumed = asyncio.Event()
        identity = SimpleNamespace(access_profile_id=ids[1], context=SimpleNamespace(), persist=AsyncMock())
        calls: list[bool] = []

        async def coordinator(reobserve_current_page: bool = False):
            calls.append(reobserve_current_page)
            if not reobserve_current_page:
                started.set()
                await asyncio.Event().wait()
            resumed.set()
            return SimpleNamespace(identity_evidence=())

        with patch("backend.services.access_profiles.record_profile_validation"):
            task = asyncio.create_task(_coordinate_owned_access(ids[2], identity, SimpleNamespace(context=identity.context), coordinator_factory=coordinator))
            await started.wait()
            request_access_attention(ids[2], reason="operator_requested")
            while _status(ids[2]) != "needs_attention":
                await asyncio.sleep(0.05)
            request_access_resume(ids[2])
            await asyncio.wait_for(resumed.wait(), timeout=2)
            await asyncio.wait_for(task, timeout=2)
        assert calls == [False, True]
        assert _status(ids[2]) == "ready"

    try:
        asyncio.run(scenario())
    finally:
        _remove(ids)


def test_batch_owner_is_persisted_without_a_second_claim():
    ids = _cycle(worker_id=None)
    try:
        bind_access_cycle_owner(ids[2], "batch-worker")
        from backend.services import access_cycles

        with access_cycles.SessionLocal() as db:
            cycle = db.get(AccessCycle, ids[2])
            assert cycle.worker_id == "batch-worker"
        bind_access_cycle_owner(ids[2], "batch-worker")
    finally:
        _remove(ids)


def test_fresh_attention_is_not_recovered_and_stale_attention_is_recoverable():
    fresh = _cycle(status="needs_attention")
    stale = _cycle(status="needs_attention")
    from backend.services import access_cycles

    try:
        with access_cycles.SessionLocal.begin() as db:
            db.get(AccessCycle, stale[2]).heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        assert recover_stale_access_cycles(datetime.now(UTC) - timedelta(seconds=60)) == 1
        assert _status(fresh[2]) == "needs_attention"
        assert _status(stale[2]) == "starting"
    finally:
        _remove(fresh)
        _remove(stale)


def test_resume_current_page_does_not_navigate_entry_url():
    class Body:
        async def inner_text(self, **_kwargs):
            return "access-test@example.test"

    page = SimpleNamespace(url="https://system.example.test/home", goto=AsyncMock(), locator=lambda _selector: Body(), frames=[])
    result = asyncio.run(
        CanonicalAccessCoordinator().start(
            page,
            external_system={"entry_url": "https://entry.example.test", "expected_system_host": "system.example.test"},
            access_profile={"id": "profile", "login_identifier": "access-test@example.test"},
            reobserve_current_page=True,
        )
    )
    assert result.state == "external_system_ready"
    page.goto.assert_not_awaited()


def test_attention_request_is_idempotent():
    ids = _cycle()
    try:
        first = request_access_attention(ids[2], reason="operator_requested")
        second = request_access_attention(ids[2], reason="different_reason")
        assert first["access_cycle_id"] == second["access_cycle_id"]
        assert second["attention_reason"] == "operator_requested"
    finally:
        _remove(ids)


def test_attention_requires_worker_owner():
    ids = _cycle(worker_id=None)
    try:
        with pytest.raises(AccessCycleError) as error:
            request_access_attention(ids[2], reason="operator_requested")
        assert error.value.code == "access_cycle_owner_missing"
    finally:
        _remove(ids)


def test_resume_requires_needs_attention_state():
    ids = _cycle()
    try:
        with pytest.raises(AccessCycleError) as error:
            request_access_resume(ids[2])
        assert error.value.code == "access_cycle_not_in_attention"
    finally:
        _remove(ids)


def test_cancelled_cycle_is_not_attention_resumable():
    ids = _cycle()
    try:
        finish_access_cycle(ids[2], status="cancelled")
        with pytest.raises(AccessCycleError) as error:
            request_access_attention(ids[2], reason="operator_requested")
        assert error.value.code == "access_cycle_not_active"
    finally:
        _remove(ids)


def test_attention_heartbeat_is_updated_without_status_reversion():
    ids = _cycle()
    try:
        request_access_attention(ids[2], reason="operator_requested")
        with __import__("backend.services.access_cycles", fromlist=["SessionLocal"]).SessionLocal.begin() as db:
            cycle = db.get(AccessCycle, ids[2])
            cycle.status = "needs_attention"
            cycle.attention_requested_at = None
        before = datetime.now(UTC) - timedelta(minutes=1)
        with __import__("backend.services.access_cycles", fromlist=["SessionLocal"]).SessionLocal.begin() as db:
            db.get(AccessCycle, ids[2]).heartbeat_at = before
        touch_access_cycle(ids[2], status="running")
        from backend.services import access_cycles
        with access_cycles.SessionLocal() as db:
            cycle = db.get(AccessCycle, ids[2])
            assert cycle.status == "needs_attention"
            assert cycle.heartbeat_at > before
    finally:
        _remove(ids)


def test_resume_does_not_create_a_new_run_or_access_cycle():
    ids = _cycle()
    try:
        request_access_attention(ids[2], reason="operator_requested")
        from backend.services import access_cycles
        with access_cycles.SessionLocal.begin() as db:
            db.get(AccessCycle, ids[2]).status = "needs_attention"
            db.get(AccessCycle, ids[2]).attention_requested_at = None
        request_access_resume(ids[2])
        with access_cycles.SessionLocal() as db:
            assert db.query(AccessCycle).count() == 1
            assert db.get(AccessCycle, ids[2]).id == ids[2]
    finally:
        _remove(ids)


def test_attention_reason_drops_secret_like_details():
    ids = _cycle()
    try:
        request_access_attention(ids[2], reason="operator_requested", details={"note": "inspect", "token": "never-store"})
        from backend.services import access_cycles
        with access_cycles.SessionLocal() as db:
            assert db.get(AccessCycle, ids[2]).attention_details == {"note": "inspect"}
    finally:
        _remove(ids)


def test_attention_preserves_worker_owner():
    ids = _cycle()
    try:
        request_access_attention(ids[2], reason="operator_requested")
        from backend.services import access_cycles
        with access_cycles.SessionLocal() as db:
            cycle = db.get(AccessCycle, ids[2])
            assert cycle.worker_id == "worker-q"
    finally:
        _remove(ids)


def test_stale_recovery_clears_attention_requests_after_owner_loss():
    ids = _cycle(status="needs_attention")
    from backend.services import access_cycles
    try:
        with access_cycles.SessionLocal.begin() as db:
            cycle = db.get(AccessCycle, ids[2])
            cycle.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
            cycle.attention_requested_at = datetime.now(UTC)
            cycle.resume_requested_at = datetime.now(UTC)
        assert recover_stale_access_cycles(datetime.now(UTC) - timedelta(seconds=60)) == 1
        with access_cycles.SessionLocal() as db:
            cycle = db.get(AccessCycle, ids[2])
            assert cycle.status == "starting"
            assert cycle.attention_requested_at is None
            assert cycle.resume_requested_at is None
    finally:
        _remove(ids)
