from __future__ import annotations

import asyncio

from backend.services.access_coordinator import _identity_evidence
from backend.services.browser_providers import BrowserIdentitySession, reset_browser_identity_sessions


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


def setup_function() -> None:
    reset_browser_identity_sessions()


def test_same_profile_reuses_session() -> None:
    context = FakeContext()

    async def scenario() -> None:
        assert await BrowserIdentitySession(context, "profile-a", scope="test").activate() is False
        assert await BrowserIdentitySession(context, "profile-a", scope="test").activate() is False

    asyncio.run(scenario())
    assert context.clear_count == 0


def test_different_profile_isolated() -> None:
    context = FakeContext()

    async def scenario() -> None:
        await BrowserIdentitySession(context, "profile-a", scope="test").activate()
        assert await BrowserIdentitySession(context, "profile-b", scope="test").activate() is True

    asyncio.run(scenario())
    assert context.clear_count == 1


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


def test_multi_output_does_not_reset_session() -> None:
    context = FakeContext()

    async def scenario() -> None:
        for _output in range(3):
            assert await BrowserIdentitySession(context, "profile-a", scope="test").activate() is False

    asyncio.run(scenario())
    assert context.clear_count == 0


def test_batch_profile_transitions_are_sequential_and_isolated() -> None:
    context = FakeContext()
    switches: list[bool] = []

    async def scenario() -> None:
        for profile_id in ("profile-a", "profile-a", "profile-b", "profile-b"):
            switches.append(await BrowserIdentitySession(context, profile_id, scope="test").activate())

    asyncio.run(scenario())
    assert switches == [False, False, True, False]
    assert context.clear_count == 1
