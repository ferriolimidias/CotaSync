"""Ensaia o ciclo completo da demo usando apenas o alvo local ficticio."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from playwright.async_api import async_playwright


API_BASE = os.getenv("COTASYNC_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BROWSERLESS_HTTP = os.getenv("COTASYNC_BROWSERLESS_HTTP_URL", "http://cotasync_test_browserless:3000").rstrip("/")
BROWSERLESS_WS = os.getenv("COTASYNC_BROWSERLESS_WS_URL", "ws://cotasync_test_browserless:3000").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
UI_MAP = ROOT / "data" / "ui_map.json"
RUNS = ROOT / "data" / "runs" / "runs.json"
ACTION_NAME = "Consultar status do pedido"
MAPPING_EVIDENCE = ROOT / "data" / "mapeamento_Consultar_status_do_pedido.png"
DEMO_SESSIONS = ROOT / "data" / "demo_sessions"


def api(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
    response = requests.request(method, f"{API_BASE}{path}", json=payload, timeout=timeout)
    if not response.ok:
        raise AssertionError(f"{method} {path} retornou {response.status_code}: {response.text}")
    body = response.json()
    assert isinstance(body, dict)
    return body


def browser_id_for(tracking_id: str) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        sessions = requests.get(f"{BROWSERLESS_HTTP}/sessions", timeout=5).json()
        for item in sessions:
            if item.get("trackingId") == tracking_id and item.get("type") == "browser":
                return str(item["browserId"])
        time.sleep(0.2)
    raise AssertionError("Sessao criada nao apareceu no Browserless.")


async def run_cycle(number: int) -> str:
    created = api("POST", "/api/demo/sessions")
    session = created["session"]
    session_id = session["id"]
    playwright = await async_playwright().start()
    browser = None
    try:
        live_parts = urlsplit(session["live_url"])
        live_response = requests.get(
            f"{BROWSERLESS_HTTP}{live_parts.path}?{live_parts.query}",
            timeout=5,
        )
        assert live_response.status_code == 200
        assert "DevTools" in live_response.text

        premature = requests.post(
            f"{API_BASE}/api/demo/sessions/{session_id}/confirm-login",
            timeout=5,
        )
        assert premature.status_code == 409

        browser_id = browser_id_for(session["tracking_id"])
        browser = await playwright.chromium.connect_over_cdp(f"{BROWSERLESS_WS}/devtools/browser/{browser_id}")
        page = next(
            page
            for context in browser.contexts
            for page in context.pages
            if "/demo/alvo" in page.url
        )

        # Representa o operador humano usando a live view. Credenciais sao somente da fixture local.
        await page.fill("#demo-user", "demo")
        await page.fill("#demo-password", "demo")
        await page.click("#demo-login")
        await page.wait_for_selector("[data-cotasync-authenticated='true']", timeout=5000)
        confirmed = api("POST", f"/api/demo/sessions/{session_id}/confirm-login")
        assert confirmed["session"]["status"] == "autenticada"
        assert (DEMO_SESSIONS / session_id / "storage_state.json").is_file()

        started = api("POST", f"/api/demo/sessions/{session_id}/recording/start")
        assert started["session"]["status"] == "gravando"
        await page.fill("#pedido-codigo", "PED-1001")
        await page.click("#buscar-pedido")
        await page.wait_for_timeout(700)

        stopped = api("POST", f"/api/demo/sessions/{session_id}/recording/stop")
        steps = stopped["steps"]
        assert [step["tipo"] for step in steps] == ["preencher", "clicar", "extrair_texto"]
        assert all("password" not in step.get("seletor", "").lower() for step in steps)
        assert all(step.get("valor") != "demo" for step in steps)

        fill_index = next(step["index"] for step in steps if step["tipo"] == "preencher")
        saved = api(
            "POST",
            f"/api/demo/sessions/{session_id}/actions",
            {
                "name": ACTION_NAME,
                "description": "Consulta um pedido ficticio e extrai seu status.",
                "variable_names": {str(fill_index): "codigo_pedido"},
            },
        )["action"]
        assert saved["steps_count"] == 3
        assert saved["variables"] == ["codigo_pedido"]
        persisted = json.loads(UI_MAP.read_text(encoding="utf-8"))["acoes_conhecidas"][ACTION_NAME]
        assert persisted["modo_aprendizado"] == "gravacao_manual"
        assert persisted["variaveis_necessarias"] == ["codigo_pedido"]
        assert persisted["passos_playwright"][0]["variavel"] == "codigo_pedido"
        assert persisted["passos_playwright"][0]["valor"] == ""
        assert "demo-password" not in json.dumps(persisted)

        catalog = api("GET", "/api/actions")
        assert any(action["id"] == saved["id"] and action["steps_count"] == 3 for action in catalog["actions"])

        replay = api(
            "POST",
            f"/api/actions/{saved['id']}/run",
            {
                "variables": {"codigo_pedido": "PED-2002"},
                "mode": "sync",
                "requested_by": "demo-cycle-test",
                "session_id": session_id,
            },
        )["run"]
        assert replay["status"] == "success", replay
        assert replay["session_id"] == session_id
        assert replay["result_payload"]["dados_extraidos"]["status_pedido"] == "Enviado"
        assert replay["result_payload"]["passos_executados"] == 3
        evidence = ROOT / replay["result_payload"]["evidencia"]
        assert evidence.is_file() and evidence.stat().st_size > 0
        assert await page.locator("#pedido-codigo").input_value() == "PED-2002"
        assert (await page.locator("#pedido-status").inner_text()).strip() == "Enviado"

        run_detail = api("GET", f"/api/runs/{replay['id']}")["run"]
        assert run_detail["status"] == "success"
        print(f"Ciclo {number}: login manual, 3 passos, replay e evidencia validados (run {replay['id']}).")
        return str(evidence)
    finally:
        try:
            api("DELETE", f"/api/demo/sessions/{session_id}")
        finally:
            await playwright.stop()


async def run_revalidation_regression() -> None:
    from backend.schemas.runs import ActionRunRequest
    from backend.services.action_runner import run_action_sync
    from backend.services.actions_repository import find_action
    from backend.services.demo_session import demo_session_manager

    created = await demo_session_manager.create()
    session_id = str(created["id"])
    session = demo_session_manager._get(session_id)
    storage_state = DEMO_SESSIONS / session_id / "storage_state.json"
    try:
        await session.page.fill("#demo-user", "demo")
        await session.page.fill("#demo-password", "demo")
        await session.page.click("#demo-login")
        await session.page.wait_for_selector("[data-cotasync-authenticated='true']", timeout=5000)
        confirmed = await demo_session_manager.confirm_login(session_id)
        assert confirmed["status"] == "autenticada"
        assert storage_state.is_file()

        action = find_action("consultar-status-do-pedido")
        assert action is not None

        # Regressao principal: somente o status interno expira; a pagina CDP continua autenticada.
        session.status = "expirada"
        assert await session.page.locator("[data-cotasync-authenticated='true']").count() == 1
        live_run = await run_action_sync(
            action,
            ActionRunRequest(
                variables={"codigo_pedido": "PED-2002"},
                requested_by="demo-revalidation-live-test",
                session_id=session_id,
            ),
        )
        assert live_run.status == "success", live_run
        assert live_run.result_payload and live_run.result_payload.get("session_revalidated") is True
        assert session.status == "autenticada"

        # Fallback: remove o cookie do contexto vivo e comprova a restauracao do arquivo salvo.
        await session.context.clear_cookies()
        await session.page.goto(session.page.url, wait_until="domcontentloaded")
        assert await session.page.locator("input[type='password']").count() == 1
        session.status = "expirada"
        restored_run = await run_action_sync(
            action,
            ActionRunRequest(
                variables={"codigo_pedido": "PED-2002"},
                requested_by="demo-revalidation-storage-test",
                session_id=session_id,
            ),
        )
        assert restored_run.status == "success", restored_run
        assert restored_run.result_payload and restored_run.result_payload.get("session_revalidated") is True
        assert session.status == "autenticada"
        assert await session.page.locator("[data-cotasync-authenticated='true']").count() == 1
        print("Regressao: replay revalidou pagina CDP ativa e restaurou storage_state.")
    finally:
        await demo_session_manager.close(session_id)
        assert not storage_state.exists()


async def main() -> None:
    ui_map_existed = UI_MAP.exists()
    runs_existed = RUNS.exists()
    ui_map_backup = UI_MAP.read_bytes() if ui_map_existed else b""
    runs_backup = RUNS.read_bytes() if runs_existed else b""
    mapping_existed = MAPPING_EVIDENCE.exists()
    mapping_backup = MAPPING_EVIDENCE.read_bytes() if mapping_existed else b""
    run_evidence_before = set((ROOT / "data" / "runs").glob("*.png"))
    try:
        for cycle in range(1, 4):
            await run_cycle(cycle)
        await run_revalidation_regression()
        print("Demo v0.1 validada em 3 ciclos consecutivos sem sistema externo.")
    finally:
        UI_MAP.parent.mkdir(parents=True, exist_ok=True)
        if ui_map_existed:
            UI_MAP.write_bytes(ui_map_backup)
        else:
            UI_MAP.unlink(missing_ok=True)
        if runs_existed:
            RUNS.parent.mkdir(parents=True, exist_ok=True)
            RUNS.write_bytes(runs_backup)
        else:
            RUNS.unlink(missing_ok=True)
        if mapping_existed:
            MAPPING_EVIDENCE.write_bytes(mapping_backup)
        else:
            MAPPING_EVIDENCE.unlink(missing_ok=True)
        for evidence in (ROOT / "data" / "runs").glob("*.png"):
            if evidence not in run_evidence_before:
                evidence.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
