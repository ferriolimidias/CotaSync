from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
import pytest

from backend.services.access_coordinator import AccessCycleError, build_microsoft_entry_url, start_canonical_access
from backend.services.start_policy import normalize_external_entry_url


class _Locator:
    def __init__(self, page, selector: str = "", text: str = ""):
        self.page = page
        self.selector = selector
        self.text = text

    @property
    def first(self):
        return self

    async def count(self):
        if self.text:
            return int(self.text in self.page.body)
        return int(self.selector in self.page.visible_selectors)

    async def is_visible(self):
        return bool(await self.count())

    async def click(self, **_kwargs):
        if self.text:
            self.page.body = "Permissions requested"
            self.page.visible_selectors = {"#accept"}
            self.page.url = "https://login.microsoftonline.com/consent"
        elif self.selector == "#accept":
            self.page.body = "External system\nworker@example.test"
            self.page.visible_selectors = set()
            self.page.url = "https://external.example.test/home"


class _Body:
    def __init__(self, page):
        self.page = page

    async def inner_text(self, **_kwargs):
        return self.page.body


class _Page:
    def __init__(self):
        self.url = "https://external.example.test/old-result"
        self.body = "old result"
        self.visible_selectors = set()
        self.goto_urls = []

    async def goto(self, url, **_kwargs):
        self.goto_urls.append(url)
        self.url = url
        self.body = "Pick an account\nworker@example.test\nSigned in"
        self.visible_selectors = set()

    async def title(self):
        return "Microsoft Account Picker"

    async def evaluate(self, _script):
        return "complete"

    def locator(self, selector):
        if selector == "body":
            return _Body(self)
        return _Locator(self, selector=selector)

    def get_by_text(self, text, **_kwargs):
        return _Locator(self, text=text)


class _AuthFrame(_Page):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def get_by_text(self, text, **_kwargs):
        locator = _Locator(self, text=text)
        original_click = locator.click

        async def click(**kwargs):
            await original_click(**kwargs)
            self.owner.body = "Permissions requested"
            self.owner.visible_selectors = {"#accept"}
            self.owner.url = "https://login.microsoftonline.com/consent"

        locator.click = click
        return locator


class _PickerInFramePage(_Page):
    def __init__(self):
        super().__init__()
        self.auth_frame = _AuthFrame(self)

    @property
    def frames(self):
        return [self, self.auth_frame]

    async def goto(self, url, **_kwargs):
        self.goto_urls.append(url)
        self.url = url
        self.body = "Microsoft shell"
        self.auth_frame.body = "Pick an account\nworker@example.test\nSigned in"


class _ConsentThenPickerPage(_Page):
    def __init__(self):
        super().__init__()
        self.goto_count = 0

    async def goto(self, url, **kwargs):
        self.goto_count += 1
        if self.goto_count == 1:
            self.url = "https://login.microsoftonline.com/consent"
            self.body = "Permissions requested"
            self.visible_selectors = {"#accept"}
            return
        await super().goto(url, **kwargs)


def test_canonical_access_selects_profile_before_learned_bootstrap():
    page = _Page()
    events = []

    def timeline(_stage, event, status, **_context):
        events.append(event)

    result = asyncio.run(
        start_canonical_access(
            page,
            external_system={
                "entry_url": "https://login.microsoftonline.com/entry",
                "expected_system_host": "external.example.test",
                "run_start_strategy": "external_entry_each_run",
            },
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
            timeline=timeline,
        )
    )

    assert result.state == "external_system_ready"
    assert events.index("ACCESS_PROFILE_SELECTION_COMPLETED") < events.index("ACCESS_BOOTSTRAP_STARTED")
    assert events.index("ACCESS_BOOTSTRAP_COMPLETED") < events.index("EXTERNAL_SYSTEM_READY")
    assert page.url == "https://external.example.test/home"


def test_canonical_access_selects_profile_rendered_in_auth_iframe():
    page = _PickerInFramePage()
    result = asyncio.run(
        start_canonical_access(
            page,
            external_system={
                "entry_url": "https://login.microsoftonline.com/entry",
                "expected_system_host": "external.example.test",
                "run_start_strategy": "external_entry_each_run",
            },
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
        )
    )
    assert result.state == "external_system_ready"
    assert page.url == "https://external.example.test/home"


def test_picker_selection_does_not_override_failed_system_identity():
    from backend.services.access_coordinator import AccessCycleError
    page = _Page()
    events = []
    with patch("backend.services.access_coordinator._identity_evidence", new=AsyncMock(return_value=False)):
        with pytest.raises(AccessCycleError) as failure:
            asyncio.run(start_canonical_access(
                page,
                external_system={"entry_url": "https://login.microsoftonline.com/entry", "expected_system_host": "external.example.test", "run_start_strategy": "external_entry_each_run"},
                access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
                action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
                timeline=lambda _stage, event, _status, **_context: events.append(event),
            ))
    assert failure.value.code == "access_identity_mismatch"
    assert "ACCESS_PROFILE_SELECTION_COMPLETED" in events
    assert "ACCESS_IDENTITY_VERIFIED" not in events
    assert "EXTERNAL_SYSTEM_READY" not in events


def test_canonical_access_never_uses_residual_page_as_start():
    page = _Page()
    asyncio.run(
        start_canonical_access(
            page,
            external_system={"entry_url": "https://login.microsoftonline.com/entry", "run_start_strategy": "external_entry_each_run"},
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
            require_external_system=False,
        )
    )
    assert page.url == "https://external.example.test/home"
    assert "old-result" not in page.url


def test_auth_learning_individual_and_batch_contract_share_state_machine():
    for context_name in ("auth", "learning", "individual", "batch-client"):
        page = _Page()
        events = []
        asyncio.run(
            start_canonical_access(
                page,
                external_system={
                    "entry_url": "https://login.microsoftonline.com/entry",
                    "expected_system_host": "external.example.test",
                    "run_start_strategy": "external_entry_each_run",
                },
                access_profile={"id": f"profile-{context_name}", "login_identifier": "worker@example.test"},
                action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
                timeline=lambda _stage, event, _status, **_ctx: events.append(event),
            )
        )
        assert events.index("ACCESS_PROFILE_SELECTION_COMPLETED") < events.index("ACCESS_BOOTSTRAP_STARTED")
        assert events.index("ACCESS_BOOTSTRAP_COMPLETED") < events.index("EXTERNAL_SYSTEM_READY")


def test_microsoft_entry_forces_picker_without_dropping_oauth_parameters():
    result = build_microsoft_entry_url(
        "https://login.microsoftonline.com/common/oauth2/authorize?client_id=c&redirect_uri=https%3A%2F%2Fapp.test%2Fcb&scope=a&response_type=code&state=s&login_hint=old%40example.test"
    )
    assert "prompt=select_account" in result
    assert "login_hint" not in result
    for required in ("client_id=c", "redirect_uri=https%3A%2F%2Fapp.test%2Fcb", "scope=a", "response_type=code", "state=s"):
        assert required in result


def test_legacy_embedded_oauth_parameter_is_repaired_without_changing_entry_authority():
    malformed = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=client"
        "&redirect_uri=https%3A%2F%2Fapp.test%2Fcallback&scope=api%3A%2F%2Fscope&state=state"
    )
    normalized = normalize_external_entry_url(malformed)
    assert normalized.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert "client_id=client" in normalized
    assert "redirect_uri=https%3A%2F%2Fapp.test%2Fcallback" in normalized
    assert "https%3A%2F%2Flogin.microsoftonline.com" not in normalized
    effective = build_microsoft_entry_url(malformed)
    assert "prompt=select_account" in effective
    assert "client_id=client" in effective


def test_canonical_entry_ignores_action_navigation_metadata():
    page = _Page()
    events = []
    asyncio.run(
        start_canonical_access(
            page,
            external_system={
                "entry_url": "https://configured.example.test/entry",
                "expected_system_host": "external.example.test",
                "run_start_strategy": "external_entry_each_run",
            },
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={"entry_url": "https://m365.cloud.microsoft/residual", "url_inicial": "https://wrong.example.test", "access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
            timeline=lambda _stage, event, _status, **context: events.append((event, context)),
            require_external_system=False,
        )
    )
    assert page.goto_urls[0] == "https://configured.example.test/entry"
    started = next(context for event, context in events if event == "CANONICAL_ENTRY_NAVIGATION_STARTED")
    assert started["canonical_entry_url_source"] == "ExternalSystem.entry_url"


def test_missing_configured_entry_does_not_fallback_to_action_url():
    page = _Page()
    try:
        asyncio.run(
            start_canonical_access(
                page,
                external_system={"run_start_strategy": "external_entry_each_run"},
                access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
                action={"entry_url": "https://m365.cloud.microsoft/residual"},
            )
        )
    except Exception as exc:
        assert getattr(exc, "code", "") == "entry_url_missing"
    else:
        raise AssertionError("A ação não pode fornecer a entry URL do sistema")


def test_batch_clients_each_get_one_entry_and_outputs_do_not_restart_entry():
    pages = [_Page(), _Page(), _Page()]
    for page in pages:
        asyncio.run(
            start_canonical_access(
                page,
                external_system={"entry_url": "https://configured.example.test/entry", "run_start_strategy": "external_entry_each_run"},
                access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
                action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
                require_external_system=False,
            )
        )
    assert [len(page.goto_urls) for page in pages] == [1, 1, 1]

    same_client = _Page()
    asyncio.run(
        start_canonical_access(
            same_client,
            external_system={"entry_url": "https://configured.example.test/entry", "run_start_strategy": "external_entry_each_run"},
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
            require_external_system=False,
        )
    )
    assert len(same_client.goto_urls) == 1


def test_direct_consent_is_restarted_until_picker_is_observed():
    page = _ConsentThenPickerPage()
    result = asyncio.run(
        start_canonical_access(
            page,
            external_system={
                "entry_url": "https://login.microsoftonline.com/entry",
                "expected_system_host": "external.example.test",
                "run_start_strategy": "external_entry_each_run",
            },
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={"access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
        )
    )
    assert result.profile_selected is True
    assert page.goto_count == 2


class _PickerLostPage(_Page):
    async def goto(self, url, **_kwargs):
        self.goto_urls.append(url)
        self.url = url
        self.body = "Pick an account\nworker@example.test"
        self.visible_selectors = set()

    def get_by_text(self, _text, **_kwargs):
        self.body = "Microsoft portal"
        self.url = "https://m365.cloud.microsoft/search"
        return _Locator(self, text="missing")


def test_picker_lost_before_explicit_selection_fails_instead_of_waiting_forever():
    page = _PickerLostPage()
    with pytest.raises(AccessCycleError) as failure:
        asyncio.run(
            start_canonical_access(
                page,
                external_system={"entry_url": "https://login.microsoftonline.com/entry", "run_start_strategy": "external_entry_each_run"},
                access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
                require_external_system=False,
            )
        )
    assert failure.value.code == "account_picker_selection_lost"
