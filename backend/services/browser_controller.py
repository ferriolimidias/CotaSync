from __future__ import annotations

from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from backend.services.browser_providers import browser_provider, desktop_browser_health


class BrowserController:
    """Interface interna fina para operar o Desktop Browser via Playwright/CDP."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def status(self) -> dict[str, Any]:
        return await desktop_browser_health()

    async def ensure_ready(self) -> Page:
        if self._page is not None and not self._page.is_closed():
            return self._page
        self._playwright = await async_playwright().start()
        connection = await browser_provider("desktop_browser").connect(self._playwright, "browser-controller")
        self._browser = connection.browser
        self._context = connection.context
        self._page = connection.page
        return self._page

    async def current_page(self) -> Page:
        return await self.ensure_ready()

    async def current_url(self) -> str:
        page = await self.ensure_ready()
        return str(page.url or "")

    async def current_title(self) -> str:
        page = await self.ensure_ready()
        return await page.title()

    async def click(self, selector: str) -> None:
        page = await self.ensure_ready()
        await page.click(selector)

    async def fill(self, selector: str, value: str) -> None:
        page = await self.ensure_ready()
        await page.fill(selector, value)

    async def insert_active(self, value: str) -> None:
        page = await self.ensure_ready()
        await page.keyboard.insert_text(value)

    async def clear_active(self) -> None:
        page = await self.ensure_ready()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")

    async def press(self, key: str) -> None:
        page = await self.ensure_ready()
        await page.keyboard.press(key)

    async def screenshot(self, path: str | None = None) -> bytes:
        page = await self.ensure_ready()
        return await page.screenshot(path=path, full_page=False)

    async def start_recording(self) -> None:
        raise NotImplementedError("Gravacao permanece no DemoSessionManager nesta rodada.")

    async def stop_recording(self) -> None:
        raise NotImplementedError("Gravacao permanece no DemoSessionManager nesta rodada.")

    async def replay(self, action_key: str, variables: dict[str, Any], run_id: str = "") -> dict[str, Any]:
        from backend.services.action_runner import _run_desktop_browser_replay
        from backend.services.actions_repository import find_action

        action = find_action(action_key)
        if action is None:
            raise RuntimeError("Acao nao encontrada.")
        return await _run_desktop_browser_replay(action, variables, run_id)

    async def recover(self) -> dict[str, Any]:
        await self.ensure_ready()
        return {"status": "ok"}

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
