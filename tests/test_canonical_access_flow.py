from __future__ import annotations

import asyncio

from backend.services.access_coordinator import start_canonical_access


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
            self.page.body = "External system"
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

    async def goto(self, url, **_kwargs):
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


def test_canonical_access_never_uses_residual_page_as_start():
    page = _Page()
    asyncio.run(
        start_canonical_access(
            page,
            external_system={"entry_url": "https://login.microsoftonline.com/entry", "run_start_strategy": "external_entry_each_run"},
            access_profile={"id": "profile-a", "login_identifier": "worker@example.test"},
            action={},
            require_external_system=False,
        )
    )
    assert page.url == "https://login.microsoftonline.com/consent"
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
