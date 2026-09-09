from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.demo_session import DemoSessionManager


class FakeCDP:
    async def send(self, method: str) -> dict[str, object]:
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": "target-picker"}}
        return {}


class FakePage:
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"

    def is_closed(self) -> bool:
        return False

    async def title(self) -> str:
        return "Pick an account"

    def on(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def goto(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("learning session creation must not navigate the existing page")


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.pages = [page]

    async def expose_binding(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def add_init_script(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def new_cdp_session(self, _page: FakePage) -> FakeCDP:
        return FakeCDP()

    def on(self, *_args: object, **_kwargs: object) -> None:
        return None


class ExistingBrowserAttachTests(unittest.TestCase):
    def test_new_learning_session_reuses_current_account_picker_page(self) -> None:
        page = FakePage()
        context = FakeContext(page)
        browser = SimpleNamespace(is_connected=lambda: True)
        runtime = SimpleNamespace(stop=AsyncMock())
        playwright_factory = SimpleNamespace(start=AsyncMock(return_value=runtime))
        provider = SimpleNamespace(
            close_browser_on_session_end=False,
            connect=AsyncMock(return_value=SimpleNamespace(browser=browser, context=context, page=page)),
            live_url=lambda _target_id: "http://desktop-browser/vnc.html",
        )
        config = {
            "id": "system-1",
            "external_system_name": "Sistema fixture",
            "external_login_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "entry_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "run_start_strategy": "external_entry_each_run",
        }
        manager = DemoSessionManager()
        with patch("backend.services.demo_session.async_playwright", return_value=playwright_factory), patch(
            "backend.services.demo_session.browser_provider", return_value=provider
        ), patch("backend.services.demo_session.configured_browser_mode", return_value="desktop_browser"), patch(
            "backend.services.external_systems.load_current_external_system", return_value=config
        ), patch("backend.services.demo_session.persist_learning_session"), patch.object(
            manager, "status", new=AsyncMock(return_value={"id": "created"})
        ):
            result = asyncio.run(manager.create())

        self.assertEqual(result["id"], "created")
        provider.connect.assert_awaited_once()
        self.assertFalse(page.url.endswith("/entry"))


if __name__ == "__main__":
    unittest.main()
