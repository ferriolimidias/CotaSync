"""Valida configuracao, aprendizado e replay em um sistema externo simulado."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from test_demo_v01_cycle import API_BASE, BROWSERLESS_WS, api, browser_id_for


ROOT = Path(__file__).resolve().parents[1]
UI_MAP = ROOT / "data" / "ui_map.json"
RUNS = ROOT / "data" / "runs" / "runs.json"
EXTERNAL_CONFIG = ROOT / "data" / "external_systems" / "current.json"
EXTERNAL_SESSIONS = ROOT / "data" / "external_systems" / "sessions"
ACTION_NAME = "Consultar pedido no sistema externo teste"
ACTION_VARIABLE = "pedido_codigo_externo"
FAKE_EXTERNAL_URL = os.getenv(
    "COTASYNC_EXTERNAL_TEST_URL", "http://cotasync_test_backend:8000/demo/alvo"
)


async def main() -> None:
    backups: dict[Path, bytes | None] = {
        path: path.read_bytes() if path.is_file() else None
        for path in (UI_MAP, RUNS, EXTERNAL_CONFIG)
    }
    evidence_before = set((ROOT / "data").glob("mapeamento_*.png")) | set(
        (ROOT / "data" / "runs").glob("*.png")
    )
    session_id = ""
    playwright = await async_playwright().start()
    browser = None
    try:
        configured = api(
            "PUT",
            "/api/external-systems/current",
            {
                "external_system_name": "Sistema Externo Teste",
                "external_login_url": FAKE_EXTERNAL_URL,
                "auth_success_text": "",
                "auth_success_selector": "[data-cotasync-authenticated='true']",
            },
        )["external_system"]
        assert configured["external_system_name"] == "Sistema Externo Teste"
        assert configured["external_login_url"] == FAKE_EXTERNAL_URL

        session = api("POST", "/api/demo/sessions")["session"]
        session_id = str(session["id"])
        assert session["using_external_system"] is True
        assert session["external_system_name"] == "Sistema Externo Teste"
        assert session["external_login_url"] == FAKE_EXTERNAL_URL
        assert session["auth_validation_mode"] == "selector"
        public_browserless = os.getenv("COTASYNC_BROWSERLESS_PUBLIC_URL", "").rstrip("/")
        if public_browserless:
            assert str(session["live_url"]).startswith(f"{public_browserless}/devtools/inspector.html")

        premature = api_raw("POST", f"/api/demo/sessions/{session_id}/confirm-login")
        assert premature.status_code == 409

        browser_id = browser_id_for(session["tracking_id"])
        browser = await playwright.chromium.connect_over_cdp(
            f"{BROWSERLESS_WS}/devtools/browser/{browser_id}"
        )
        page = next(
            page
            for context in browser.contexts
            for page in context.pages
            if "/demo/alvo" in page.url
        )
        await page.fill("#demo-user", "demo")
        await page.fill("#demo-password", "demo")
        await page.click("#demo-login")
        await page.wait_for_selector("[data-cotasync-authenticated='true']", timeout=5000)

        confirmed = api("POST", f"/api/demo/sessions/{session_id}/confirm-login")["session"]
        assert confirmed["status"] == "autenticada"
        assert confirmed["storage_state_saved"] is True
        storage_states = list(EXTERNAL_SESSIONS.glob(f"*/{session_id}/storage_state.json"))
        assert len(storage_states) == 1 and storage_states[0].stat().st_size > 0

        api("POST", f"/api/demo/sessions/{session_id}/recording/start")
        await page.fill("#pedido-codigo", "PED-1001")
        await page.click("#buscar-pedido")
        await page.wait_for_timeout(700)
        stopped = api("POST", f"/api/demo/sessions/{session_id}/recording/stop")
        steps = stopped["steps"]
        assert [step["tipo"] for step in steps] == ["preencher", "clicar", "extrair_texto"]
        fill_index = next(step["index"] for step in steps if step["tipo"] == "preencher")

        saved = api(
            "POST",
            f"/api/demo/sessions/{session_id}/actions",
            {
                "name": ACTION_NAME,
                "description": "Fluxo externo simulado com observacao ao vivo.",
                "variable_names": {str(fill_index): ACTION_VARIABLE},
            },
            timeout=40,
        )["action"]
        assert saved["external_system_name"] == "Sistema Externo Teste"
        assert saved["external_login_url"] == FAKE_EXTERNAL_URL
        assert saved["learning_mode"] == "human_demo_live_ai_observed"
        assert str(saved["ai_observer_summary"]).strip()

        persisted = json.loads(UI_MAP.read_text(encoding="utf-8"))["acoes_conhecidas"][ACTION_NAME]
        for key in (
            "external_system_name",
            "external_login_url",
            "learning_mode",
            "ai_reviewed",
            "ai_observer_summary",
            "replay_hints",
            "waits",
            "wait_strategies",
        ):
            assert key in persisted
        assert persisted["external_system_name"] == "Sistema Externo Teste"
        assert persisted["external_login_url"] == FAKE_EXTERNAL_URL
        assert persisted["replay_hints"] and persisted["waits"] and persisted["wait_strategies"]
        catalog_action = next(
            item for item in api("GET", "/api/actions")["actions"] if item["id"] == saved["id"]
        )
        assert catalog_action["external_system_name"] == "Sistema Externo Teste"
        assert catalog_action["external_login_url"] == FAKE_EXTERNAL_URL

        replay = api(
            "POST",
            f"/api/actions/{saved['id']}/run",
            {
                "variables": {ACTION_VARIABLE: "PED-2002"},
                "mode": "sync",
                "requested_by": "external-system-cycle-test",
                "session_id": session_id,
            },
            timeout=40,
        )["run"]
        assert replay["status"] == "success", replay
        assert replay["session_id"] == session_id
        assert replay["result_payload"]["dados_extraidos"]["status_pedido"] == "Enviado"
        assert await page.locator("#pedido-codigo").input_value() == "PED-2002"
        print(
            "Sistema externo: configuracao, seletor de login, storage_state, metadados, "
            "observador IA e replay validados."
        )
    finally:
        if session_id:
            try:
                api("DELETE", f"/api/demo/sessions/{session_id}")
            except Exception:
                pass
        if browser is not None:
            await browser.close()
        await playwright.stop()
        for path, content in backups.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        for evidence in set((ROOT / "data").glob("mapeamento_*.png")) | set(
            (ROOT / "data" / "runs").glob("*.png")
        ):
            if evidence not in evidence_before:
                evidence.unlink(missing_ok=True)
        if session_id:
            for session_dir in EXTERNAL_SESSIONS.glob(f"*/{session_id}"):
                shutil.rmtree(session_dir, ignore_errors=True)


def api_raw(method: str, path: str):
    import requests

    return requests.request(method, f"{API_BASE}{path}", timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
