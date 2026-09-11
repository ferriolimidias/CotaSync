"""Opt-in CDP contract: synthetic pages only, never the user's current page."""

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest
from playwright.async_api import async_playwright

from backend.db import AccessCycle, SessionLocal
from backend.main import app
from backend.services.auth import require_user
from backend.services.access_cycles import _coordinate_owned_access, get_access_cycle, validate_current_profile_session
from backend.services.browser_providers import BrowserIdentitySession, _desktop_version, browser_page_identity
from tests.test_manual_access_validation import _cycle, _remove


@pytest.mark.skipif(os.getenv("COTASYNC_CDP_CONTRACT_TEST") != "1", reason="Explicit opt-in required for synthetic contexts on desktop CDP")
def test_real_cdp_manual_validation_uses_worker_page(tmp_path):
    ids = _cycle("https://system.example.test/home")

    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(_desktop_version()["webSocketDebuggerUrl"])
            identity = BrowserIdentitySession(None, ids[1], browser=browser, storage_root=tmp_path)
            await identity.activate()
            page = await identity.page()
            task = None
            try:
                # All requests stay synthetic; no Microsoft or operational page
                # receives navigation, clicks, or injected scripts.
                await page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<body>priscila@example.test</body>"))
                await page.goto("https://system.example.test/home")
                await identity.context.add_cookies([{"name": "contract", "value": "profile-only", "url": "https://system.example.test"}])
                target = await browser_page_identity(identity.context, page)
                with SessionLocal.begin() as db:
                    cycle = db.get(AccessCycle, ids[2])
                    cycle.browser_target_id = target["target_id"]
                    cycle.browser_context_id = target["context_id"]
                started = asyncio.Event()
                stopped = asyncio.Event()

                async def waiting_coordinator():
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        stopped.set()

                task = asyncio.create_task(_coordinate_owned_access(ids[2], identity, page, waiting_coordinator()))
                await started.wait()
                app.dependency_overrides[require_user] = lambda: SimpleNamespace(id="test-admin", role="admin")
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    login = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password"})
                    assert login.status_code == 200
                    response = await client.post(f"/api/v1/access-cycles/{ids[2]}/validate-manual", headers={"X-CSRF-Token": login.json()["csrf_token"]})
                assert response.status_code == 200
                assert response.json()["status"] == "validation_requested"
                await asyncio.wait_for(task, timeout=5)
                assert stopped.is_set()
                assert get_access_cycle(ids[2])["status"] == "ready"
                assert await browser_page_identity(identity.context, page) == target
                assert identity.storage_path.is_file()
                assert not page.is_closed()
                passive = await validate_current_profile_session(ids[1])
                assert passive["available"] is True
                assert await browser_page_identity(identity.context, page) == target
                other = await browser.new_context()
                try:
                    assert not await other.cookies("https://system.example.test")
                finally:
                    await other.close()
            finally:
                app.dependency_overrides.pop(require_user, None)
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await identity.context.close()

    try:
        asyncio.run(scenario())
    finally:
        _remove(ids)
