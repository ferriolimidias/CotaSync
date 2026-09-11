from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.db import Action, ActionVersion, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_coordinator import _identity_evidence
from backend.services.browser_providers import BrowserIdentitySession, BrowserProviderError, reset_browser_identity_sessions, supports_isolated_browser_contexts
from backend.services.actions_repository import save_learned_action


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def is_closed(self) -> bool:
        return False

    def locator(self, _selector: str):
        page = self

        class Locator:
            async def inner_text(self, **_kwargs):
                return page.text

        return Locator()

    async def evaluate(self, _script: str) -> None:
        return None


class FakeContext:
    def __init__(self) -> None:
        self.pages = [FakePage("external system")]
        self.clear_count = 0

    async def clear_cookies(self) -> None:
        self.clear_count += 1


class StorageContext(FakeContext):
    def __init__(self, state: str = "") -> None:
        super().__init__()
        self.state = state

    async def storage_state(self, *, path: str, indexed_db: bool = False) -> None:
        assert indexed_db is True
        Path(path).write_text(json.dumps({"state": self.state}), encoding="utf-8")


class StorageBrowser:
    async def new_context(self, **options):
        state_path = options.get("storage_state")
        state = ""
        if state_path:
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))["state"]
        return StorageContext(state)


def setup_function() -> None:
    reset_browser_identity_sessions()


def test_new_context_available(tmp_path) -> None:
    context = FakeContext()
    browser = StorageBrowser()

    async def scenario() -> None:
        identity = BrowserIdentitySession(context, "profile-a", browser=browser, storage_root=tmp_path, scope="test")
        assert await identity.activate() is False
        assert identity.profile_context is not None

    asyncio.run(scenario())
    assert supports_isolated_browser_contexts(browser) is True


def test_new_context_unavailable_fails_closed() -> None:
    context = FakeContext()

    async def scenario() -> None:
        with pytest.raises(BrowserProviderError) as error:
            await BrowserIdentitySession(context, "profile-a", scope="test").activate()
        assert error.value.code == "ACCESS_PROFILE_BROWSER_ISOLATION_UNAVAILABLE"

    asyncio.run(scenario())
    assert context.clear_count == 0
    assert supports_isolated_browser_contexts(context) is False


def test_no_global_context_profile_fallback() -> None:
    context = FakeContext()

    async def scenario() -> None:
        with pytest.raises(BrowserProviderError):
            await BrowserIdentitySession(context, "profile-a", scope="test").activate()

    asyncio.run(scenario())
    assert context.clear_count == 0


def test_profile_storage_isolation(tmp_path) -> None:
    browser = StorageBrowser()
    base = FakeContext()

    async def scenario() -> None:
        priscila = BrowserIdentitySession(base, "profile-priscila", browser=browser, storage_root=tmp_path, scope="storage")
        await priscila.activate()
        assert isinstance(priscila.context, StorageContext)
        priscila.context.state = "state-priscila"
        await priscila.persist()

        joao = BrowserIdentitySession(base, "profile-joao", browser=browser, storage_root=tmp_path, scope="storage")
        await joao.activate()
        assert isinstance(joao.context, StorageContext)
        assert joao.context.state == ""
        joao.context.state = "state-joao"
        await joao.persist()

    asyncio.run(scenario())
    assert (tmp_path / BrowserIdentitySession(base, "profile-priscila", storage_root=tmp_path).storage_path.name).is_file()
    assert (tmp_path / BrowserIdentitySession(base, "profile-joao", storage_root=tmp_path).storage_path.name).is_file()


def test_profile_storage_roundtrip(tmp_path) -> None:
    browser = StorageBrowser()
    base = FakeContext()

    async def scenario() -> None:
        first = BrowserIdentitySession(base, "profile-priscila", browser=browser, storage_root=tmp_path, scope="roundtrip")
        await first.activate()
        first.context.state = "original-priscila"
        await first.persist()
        await BrowserIdentitySession(base, "profile-joao", browser=browser, storage_root=tmp_path, scope="roundtrip").activate()
        restored = BrowserIdentitySession(base, "profile-priscila", browser=browser, storage_root=tmp_path, scope="roundtrip")
        await restored.activate()
        assert restored.context.state == "original-priscila"

    asyncio.run(scenario())


def test_identity_match() -> None:
    page = FakePage("signed in as Priscila")
    assert asyncio.run(
        _identity_evidence(
            page,
            {"login_identifier": "priscila@example.test", "display_name": "Priscila"},
            {},
        )
    ) is True


def test_identity_mismatch_with_configured_marker() -> None:
    class Locator:
        first = None

        async def inner_text(self, **_kwargs):
            return "Priscila"

    class Page:
        def locator(self, _selector):
            return Locator()

    assert asyncio.run(
        _identity_evidence(
            Page(),
            {"login_identifier": "joao@example.test", "display_name": "Joao"},
            {"identity_selector": "[data-current-user]"},
        )
    ) is False


def test_multi_output_does_not_reset_session(tmp_path) -> None:
    context = FakeContext()
    browser = StorageBrowser()

    async def scenario() -> None:
        for _output in range(3):
            assert await BrowserIdentitySession(context, "profile-a", browser=browser, storage_root=tmp_path, scope="outputs").activate() is False

    asyncio.run(scenario())
    assert context.clear_count == 0


def test_batch_profile_transitions_are_sequential_and_isolated(tmp_path) -> None:
    context = FakeContext()
    browser = StorageBrowser()
    switches: list[bool] = []

    async def scenario() -> None:
        for profile_id in ("profile-a", "profile-a", "profile-b", "profile-b"):
            switches.append(await BrowserIdentitySession(context, profile_id, browser=browser, storage_root=tmp_path, scope="batch").activate())

    asyncio.run(scenario())
    assert switches == [False, False, True, False]


def test_learning_publication_binds_profile_and_keeps_previous_version() -> None:
    suffix = uuid4().hex
    system_a = f"system-{suffix}-a"
    system_b = f"system-{suffix}-b"
    profile_a = f"profile-{suffix}-a"
    profile_b = f"profile-{suffix}-b"
    action_key = f"profile-bound-{suffix}"
    action_id = action_key
    try:
        with SessionLocal.begin() as db:
            db.add(ExternalSystem(id=system_a, name=system_a, config={"entry_url": "https://entry.example.test", "run_start_strategy": "external_entry_each_run"}))
            db.add(ExternalSystem(id=system_b, name=system_b, config={"entry_url": "https://entry.example.test", "run_start_strategy": "external_entry_each_run"}))
            db.flush()
            db.add(ExternalAccessProfile(id=profile_a, tenant_id="default", external_system_id=system_a, display_name="A", login_identifier=f"a-{suffix}@example.test", active=True))
            db.add(ExternalAccessProfile(id=profile_b, tenant_id="default", external_system_id=system_b, display_name="B", login_identifier=f"b-{suffix}@example.test", active=True))
        first = save_learned_action(action_key, {"nome_amigavel": action_key, "external_system_id": system_a, "required_access_profile_id": profile_a, "run_start_strategy": "external_entry_each_run", "robust_steps": [{"tipo": "clicar", "seletor": "#a"}]})
        second = save_learned_action(action_key, {"nome_amigavel": action_key, "external_system_id": system_b, "required_access_profile_id": profile_b, "run_start_strategy": "external_entry_each_run", "robust_steps": [{"tipo": "clicar", "seletor": "#b"}]})
        with SessionLocal() as db:
            action = db.get(Action, action_id)
            assert action is not None
            assert first.id == action_id and second.id == action_id
            assert action.published_version_id == f"{action_id}-v2"
            assert db.get(ActionVersion, f"{action_id}-v1").required_access_profile_id == profile_a
            assert db.get(ActionVersion, f"{action_id}-v2").required_access_profile_id == profile_b
    finally:
        with SessionLocal.begin() as db:
            db.query(ActionVersion).filter(ActionVersion.action_id == action_id).delete(synchronize_session=False)
            db.query(Action).filter(Action.id == action_id).delete(synchronize_session=False)
            db.query(ExternalAccessProfile).filter(ExternalAccessProfile.id.in_([profile_a, profile_b])).delete(synchronize_session=False)
            db.query(ExternalSystem).filter(ExternalSystem.id.in_([system_a, system_b])).delete(synchronize_session=False)
