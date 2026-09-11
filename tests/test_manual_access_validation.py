from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from backend.db import AccessCycle, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_cycles import validate_manual_access_cycle, _validate_owned_access_cycle, _coordinate_owned_access, touch_access_cycle
from backend.services.access_profiles import validate_profile_from_observation


class _BodyLocator:
    def __init__(self, text: str) -> None:
        self.text = text

    async def inner_text(self, **_kwargs):
        return self.text


class _Page:
    def __init__(self, url: str, body: str = "") -> None:
        self.url = url
        self.body = body
        self.goto = AsyncMock(side_effect=AssertionError("manual validation must not navigate"))

    def is_closed(self):
        return False

    def locator(self, selector: str):
        assert selector == "body"
        return _BodyLocator(self.body)


class _Context:
    def __init__(self, page: _Page) -> None:
        self.pages = [page]
        page.context = self

    async def storage_state(self, **_kwargs):
        return None


class _Browser:
    def __init__(self, context: _Context) -> None:
        self.context = context

    async def new_context(self, **_kwargs):
        return self.context


def _cycle(page_url: str, page_body: str = "") -> tuple[str, str, str, _Page]:
    suffix = uuid4().hex
    system_id, profile_id, cycle_id = f"manual-system-{suffix}", f"manual-profile-{suffix}", f"manual-cycle-{suffix}"
    with SessionLocal.begin() as db:
        db.add(ExternalSystem(id=system_id, name=system_id, config={"entry_url": "https://login.example.test", "expected_system_host": "system.example.test"}))
        db.flush()
        db.add(ExternalAccessProfile(id=profile_id, tenant_id="default", external_system_id=system_id, display_name="Priscila", login_identifier="priscila@example.test", active=True))
        db.flush()
        db.add(AccessCycle(id=cycle_id, external_system_id=system_id, access_profile_id=profile_id, entry_url="https://login.example.test", status="waiting", stage="manual_authentication", events=[], browser_target_id="owned-target", browser_context_id="owned-context"))
    return system_id, profile_id, cycle_id, _Page(page_url, page_body)


def _remove(ids: tuple[str, str, str, _Page]) -> None:
    with SessionLocal.begin() as db:
        for model, item_id in ((AccessCycle, ids[2]), (ExternalAccessProfile, ids[1]), (ExternalSystem, ids[0])):
            row = db.get(model, item_id)
            if row is not None:
                db.delete(row)


def _provider(page: _Page):
    context = _Context(page)
    browser = _Browser(context)
    playwright = SimpleNamespace(stop=AsyncMock())
    factory = SimpleNamespace(start=AsyncMock(return_value=playwright))
    provider = SimpleNamespace(connect=AsyncMock(return_value=SimpleNamespace(context=context, browser=browser, page=page)))
    return factory, provider


async def _validate_fixture(ids):
    context = _Context(ids[3])
    identity = SimpleNamespace(access_profile_id=ids[1], context=context, persist=AsyncMock())
    result = await _validate_owned_access_cycle(ids[2], identity, ids[3])
    if result["validated"]:
        identity.persist.assert_awaited_once()
    else:
        identity.persist.assert_not_awaited()
    return result


def test_manual_auth_validate_success() -> None:
    ids = _cycle("https://system.example.test/home")
    factory, provider = _provider(ids[3])
    try:
        with patch("backend.services.access_cycles.async_playwright", return_value=factory), patch("backend.services.access_cycles.browser_provider", return_value=provider), patch("backend.services.access_cycles._identity_evidence", new=AsyncMock(return_value=True)):
            result = asyncio.run(_validate_fixture(ids))
        assert result["validated"] is True
        with SessionLocal() as db:
            cycle = db.get(AccessCycle, ids[2])
            profile = db.get(ExternalAccessProfile, ids[1])
            assert cycle is not None and cycle.status == "ready"
            assert profile is not None and profile.validation_status == "verified"
    finally:
        _remove(ids)


def test_validate_before_auth_complete_returns_structured_wait() -> None:
    ids = _cycle("https://login.example.test/consent", "Permissions requested")
    factory, provider = _provider(ids[3])
    try:
        with patch("backend.services.access_cycles.async_playwright", return_value=factory), patch("backend.services.access_cycles.browser_provider", return_value=provider):
            result = asyncio.run(_validate_fixture(ids))
        assert result["code"] == "ACCESS_AUTHENTICATION_NOT_COMPLETED"
        with SessionLocal() as db:
            assert db.get(AccessCycle, ids[2]).status == "waiting"
    finally:
        _remove(ids)


def test_validate_wrong_identity_does_not_complete_cycle() -> None:
    ids = _cycle("https://system.example.test/home")
    factory, provider = _provider(ids[3])
    try:
        with patch("backend.services.access_cycles.async_playwright", return_value=factory), patch("backend.services.access_cycles.browser_provider", return_value=provider), patch("backend.services.access_cycles._identity_evidence", new=AsyncMock(return_value=False)):
            result = asyncio.run(_validate_fixture(ids))
        assert result["code"] == "ACCESS_IDENTITY_MISMATCH"
        with SessionLocal() as db:
            cycle = db.get(AccessCycle, ids[2])
            assert cycle is not None and cycle.status == "waiting"
    finally:
        _remove(ids)


def test_validate_does_not_navigate_current_page() -> None:
    ids = _cycle("https://system.example.test/home")
    factory, provider = _provider(ids[3])
    try:
        with patch("backend.services.access_cycles.async_playwright", return_value=factory), patch("backend.services.access_cycles.browser_provider", return_value=provider), patch("backend.services.access_cycles._identity_evidence", new=AsyncMock(return_value=True)):
            asyncio.run(_validate_fixture(ids))
        ids[3].goto.assert_not_awaited()
    finally:
        _remove(ids)


def test_learning_can_use_the_same_manual_validation_operation() -> None:
    ids = _cycle("https://system.example.test/home")
    factory, provider = _provider(ids[3])
    try:
        with patch("backend.services.access_cycles.async_playwright", return_value=factory), patch("backend.services.access_cycles.browser_provider", return_value=provider), patch("backend.services.access_cycles._identity_evidence", new=AsyncMock(return_value=True)):
            result = asyncio.run(_validate_fixture(ids))
        assert result["access_cycle"]["stage"] == "external_system_ready"
    finally:
        _remove(ids)


def test_profile_card_validate_remains_passive() -> None:
    observation = SimpleNamespace(browser_available=True, page_available=True, body_text="Pick an account")
    with patch("backend.services.access_profiles.record_profile_validation", return_value={"id": "profile", "validation_status": "unknown"}) as persist:
        result = validate_profile_from_observation({"id": "profile", "login_identifier": "profile@example.test"}, observation)
    persist.assert_called_once()
    assert result["available"] is False


def test_manual_request_is_worker_owned_and_stops_automation():
    ids = _cycle("https://system.example.test/home", "priscila@example.test")

    async def scenario():
        started = asyncio.Event()
        stopped = asyncio.Event()
        context = _Context(ids[3])
        identity = SimpleNamespace(access_profile_id=ids[1], context=context, persist=AsyncMock())

        async def slow_access():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        task = asyncio.create_task(_coordinate_owned_access(ids[2], identity, ids[3], slow_access()))
        await started.wait()
        with patch("backend.services.access_cycles.async_playwright", side_effect=AssertionError("HTTP must not connect")):
            result = await validate_manual_access_cycle(ids[2])
        assert result["status"] == "validation_requested"
        await asyncio.wait_for(task, timeout=3)
        assert stopped.is_set()
        identity.persist.assert_awaited_once()
        touch_access_cycle(ids[2], status="waiting")
        with SessionLocal() as db:
            assert db.get(AccessCycle, ids[2]).status == "ready"

    try:
        asyncio.run(scenario())
    finally:
        _remove(ids)


def test_manual_validation_missing_binding_fails_closed():
    ids = _cycle("https://system.example.test/home")
    try:
        with SessionLocal.begin() as db:
            db.get(AccessCycle, ids[2]).browser_target_id = None
        from backend.services.access_coordinator import AccessCycleError
        try:
            asyncio.run(validate_manual_access_cycle(ids[2]))
        except AccessCycleError as exc:
            assert exc.code == "ACCESS_CYCLE_SESSION_UNAVAILABLE"
        else:
            raise AssertionError("Unowned session accepted")
    finally:
        _remove(ids)


def test_passive_unbound_profile_does_not_inspect_global_page():
    from backend.services.access_cycles import validate_current_profile_session
    ids = _cycle("https://system.example.test/home")
    try:
        with SessionLocal.begin() as db:
            db.get(AccessCycle, ids[2]).browser_target_id = None
            db.get(ExternalAccessProfile, ids[1]).validation_status = "verified"
        with patch("backend.services.access_cycles.async_playwright", side_effect=AssertionError("No global browser fallback")):
            result = asyncio.run(validate_current_profile_session(ids[1]))
        assert result["available"] is False
        assert result["profile"]["validation_status"] == "verified"
    finally:
        _remove(ids)
