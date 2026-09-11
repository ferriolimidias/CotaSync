"""Real CDP reattachment: the reader must not instrument another profile."""

import asyncio
import os
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright

from backend.db import AccessCycle, SessionLocal
from backend.services import demo_session
from backend.services.browser_providers import _desktop_version, browser_page_identity
from backend.services.demo_session import DemoBrowserSession, DemoSessionError, DemoSessionManager
from tests.test_manual_access_validation import _cycle, _remove


@pytest.mark.skipif(os.getenv("COTASYNC_CDP_CONTRACT_TEST") != "1", reason="Requires separate synthetic CDP browser")
def test_learning_reattaches_only_verified_profile_page(tmp_path, monkeypatch):
    ids = _cycle("https://system.example.test/home")
    monkeypatch.setattr(demo_session, "persist_learning_session", lambda session: None)

    async def scenario():
        endpoint = _desktop_version()["webSocketDebuggerUrl"]
        async with async_playwright() as owner:
            browser = await owner.chromium.connect_over_cdp(endpoint)
            own_context = await browser.new_context()
            other_context = await browser.new_context()
            try:
                owned = await own_context.new_page()
                foreign = await other_context.new_page()
                async def route_learning(route):
                    body = '<input id="group"><input id="quota"><button id="search">Search</button>' if route.request.url.endswith("/fields") else '<input id="next-field">'
                    await route.fulfill(status=200, content_type="text/html", body=body)
                await owned.route("https://learning.example.test/**", route_learning)
                await owned.set_content('<a id="query" href="https://learning.example.test/next">Query</a>')
                await foreign.set_content('<button id="private">Other profile</button>')
                identity = await browser_page_identity(own_context, owned)
                with SessionLocal.begin() as db:
                    cycle = db.get(AccessCycle, ids[2])
                    cycle.browser_target_id = identity["target_id"]
                    cycle.browser_context_id = identity["context_id"]
                async with async_playwright() as reader:
                    attached = await reader.chromium.connect_over_cdp(endpoint)
                    manager = DemoSessionManager()
                    session = DemoBrowserSession(
                        id="synthetic-handoff", playwright=reader, browser=attached,
                        context=attached.contexts[0], page=attached.contexts[0].pages[0],
                        target_id="residual", live_url="", created_at="", tracking_id="",
                        access_profile_id=ids[1], access_cycle_id=ids[2],
                        storage_state_path=tmp_path / "storage.json",
                    )
                    manager._sessions[session.id] = session
                    with pytest.raises(DemoSessionError):
                        await manager._enable_learning_recording(session)
                    assert not session.recording
                    session.status = "interrupted"
                    with pytest.raises(DemoSessionError):
                        await manager.resume_recording(session.id)
                    assert not session.recording
                    assert not await owned.evaluate("Boolean(window.__cotasyncRecorderInstalled)")
                    with SessionLocal.begin() as db:
                        cycle = db.get(AccessCycle, ids[2])
                        cycle.status = "ready"
                        cycle.stage = "external_system_ready"
                    await manager._enable_learning_recording(session)
                    assert session.target_id == identity["target_id"]
                    assert await owned.evaluate("Boolean(window.__cotasyncRecorderInstalled)")
                    assert not await foreign.evaluate("Boolean(window.__cotasyncRecorderInstalled)")
                    assert len(await manager._recording_pages(session)) == 1
                    assert await manager._record_live_step(session, {"tipo": "clicar"}, {"page": foreign}) is None
                    assert session.steps == []
                    captured = asyncio.Event()
                    record = manager._record_live_step
                    async def receive(*args, **kwargs):
                        await record(*args, **kwargs)
                        captured.set()
                    manager._record_live_step = AsyncMock(side_effect=receive)
                    await owned.locator("#query").click()
                    await asyncio.wait_for(captured.wait(), 3)
                    assert owned.url == "https://learning.example.test/next"
                    assert manager._record_live_step.call_count == 1
                    assert len(session.learning_events) == 1
                    click = session.learning_events[0]
                    assert click["event_type"] == "click"
                    assert click["before_state_id"] != click["after_state_id"]
                    captured.clear()
                    await owned.locator("#next-field").fill("00")
                    await asyncio.wait_for(captured.wait(), 5)
                    assert len(session.learning_events) == 2
                    assert click["after_state_id"] == session.learning_events[1]["before_state_id"]
                    await owned.goto("https://learning.example.test/fields")
                    await manager._install_recorder_for_session(session)
                    await owned.locator("#group").fill("935")
                    await owned.locator("#quota").fill("438")
                    await owned.locator("#search").click()
                    for _ in range(30):
                        if len(session.learning_events) >= 5:
                            break
                        await asyncio.sleep(0.1)
                    events = session.learning_events[-3:]
                    assert [event["event_type"] for event in events] == ["fill", "fill", "click"]
                    assert events[0]["selector"] == "#group"
                    assert events[1]["selector"] == "#quota"
                    assert events[2]["selector"] == "#search"
                    session.recording = False
                    for task in list(session.observer_tasks):
                        task.cancel()
                    await asyncio.gather(*session.observer_tasks, return_exceptions=True)
            finally:
                await own_context.close()
                await other_context.close()

    try:
        asyncio.run(scenario())
    finally:
        _remove(ids)
