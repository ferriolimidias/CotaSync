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
ACTION_VARIABLE = "pedido_codigo"
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


async def run_cycle(
    number: int,
    *,
    replace_live_page: bool = False,
    emulate_devtools_live_view: bool = False,
) -> str:
    created = api("POST", "/api/demo/sessions")
    session = created["session"]
    session_id = session["id"]
    playwright = await async_playwright().start()
    browser = None
    viewer_browser = None
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
        if emulate_devtools_live_view:
            # O gesto humano na live view nao aguarda o ack de Input.dispatchMouseEvent.
            await page.locator("#buscar-pedido").evaluate("element => element.click()")
        else:
            await page.click("#buscar-pedido")
        await page.wait_for_timeout(700)

        stopped = api("POST", f"/api/demo/sessions/{session_id}/recording/stop")
        steps = stopped["steps"]
        learning_events = stopped["learning_events"]
        assert [step["tipo"] for step in steps] == ["preencher", "clicar", "extrair_texto"]
        assert len(learning_events) >= 3
        meaningful_events = {
            event["event_type"]: event
            for event in learning_events
            if event.get("event_type") in {"fill", "click", "extract"}
        }
        assert set(meaningful_events) == {"fill", "click", "extract"}
        for event in meaningful_events.values():
            assert event["elapsed_ms"] >= 0
            assert event["url_before"].endswith("/demo/alvo")
            assert event["url_after"].endswith("/demo/alvo")
            assert isinstance(event["dom_summary_before"], dict) and event["dom_summary_before"]
            assert isinstance(event["dom_summary_after"], dict) and event["dom_summary_after"]
            assert event["screenshot_before_path"]
            assert event["screenshot_after_path"]
            assert event["wait_hint"] and event["replay_hint"] and event["ai_note"]
        assert all("password" not in step.get("seletor", "").lower() for step in steps)
        assert all(step.get("valor") != "demo" for step in steps)

        fill_index = next(step["index"] for step in steps if step["tipo"] == "preencher")
        saved = api(
            "POST",
            f"/api/demo/sessions/{session_id}/actions",
            {
                "name": ACTION_NAME,
                "description": "Consulta um pedido ficticio e extrai seu status.",
                "variable_names": {str(fill_index): ACTION_VARIABLE},
            },
        )["action"]
        assert saved["steps_count"] == 3
        assert saved["variables"] == [ACTION_VARIABLE]
        persisted = json.loads(UI_MAP.read_text(encoding="utf-8"))["acoes_conhecidas"][ACTION_NAME]
        assert persisted["modo_aprendizado"] == "gravacao_manual_observada_por_ia_em_tempo_real"
        assert persisted["learning_mode"] == "human_demo_live_ai_observed"
        assert isinstance(persisted["ai_reviewed"], bool)
        assert str(persisted["ai_observer_summary"]).strip()
        assert isinstance(persisted["replay_hints"], list) and persisted["replay_hints"]
        assert isinstance(persisted["waits"], list) and persisted["waits"]
        assert isinstance(persisted["variable_schema"], list) and persisted["variable_schema"]
        assert persisted["extraction_target"]
        assert len(persisted["robust_steps"]) == 3
        assert len(persisted["learning_events"]) >= 3
        assert persisted["wait_strategies"]
        assert persisted["risks_detected"]
        assert persisted["slow_system_notes"]
        assert persisted["new_tab_or_popup_notes"]
        assert persisted["variaveis_necessarias"] == [ACTION_VARIABLE]
        assert persisted["passos_playwright"][0]["variavel"] == ACTION_VARIABLE
        assert persisted["passos_playwright"][0]["valor"] == ""
        assert persisted["url_inicial"].endswith("/demo/alvo")
        assert "demo-password" not in json.dumps(persisted)
        assert "PED-1001" not in json.dumps(persisted)
        assert saved["learning_mode"] == "human_demo_live_ai_observed"
        assert str(saved["ai_observer_summary"]).strip()

        catalog = api("GET", "/api/actions")
        assert any(
            action["id"] == saved["id"]
            and action["steps_count"] == 3
            and action["learning_mode"] == "human_demo_live_ai_observed"
            and action["ai_observer_summary"]
            for action in catalog["actions"]
        )

        if replace_live_page:
            replacement_page = await page.context.new_page()
            await replacement_page.goto(page.url, wait_until="domcontentloaded")
            await replacement_page.wait_for_selector("[data-cotasync-authenticated='true']", timeout=5000)
            await page.close()
            page = replacement_page

        if emulate_devtools_live_view:
            cdp = await page.context.new_cdp_session(page)
            target_info = await cdp.send("Target.getTargetInfo")
            target_id = str(target_info["targetInfo"]["targetId"])
            viewer_browser = await playwright.chromium.connect_over_cdp(
                f"{BROWSERLESS_WS}?trackingId=cotasync-test-viewer-{session_id[:8]}&timeout=600000"
            )
            viewer_context = viewer_browser.contexts[0]
            viewer_page = viewer_context.pages[0] if viewer_context.pages else await viewer_context.new_page()
            inspector_url = (
                f"{BROWSERLESS_HTTP}/devtools/inspector.html"
                f"?ws=cotasync_test_browserless:3000/devtools/page/{target_id}"
            )
            await viewer_page.goto(inspector_url, wait_until="domcontentloaded", timeout=10000)
            await viewer_page.wait_for_timeout(1000)

        replay = api(
            "POST",
            f"/api/actions/{saved['id']}/run",
            {
                "variables": {ACTION_VARIABLE: "PED-2002"},
                "mode": "sync",
                "requested_by": "demo-cycle-test",
                "session_id": session_id,
            },
        )["run"]
        assert replay["status"] == "success", replay
        assert replay["session_id"] == session_id
        if replace_live_page:
            assert replay["result_payload"]["session_revalidated"] is True
        assert replay["result_payload"]["dados_extraidos"]["status_pedido"] == "Enviado"
        assert replay["result_payload"]["passos_executados"] == 3
        diagnostics = replay["result_payload"]["selector_diagnostics"]
        assert [item["selector"] for item in diagnostics] == [
            "#pedido-codigo",
            "#buscar-pedido",
            "#pedido-status",
        ]
        assert all(item["count"] == 1 and item["visible"] and item["enabled"] for item in diagnostics)
        assert diagnostics[1]["click_confirmation"] in {"cdp", "dom_event_after_cdp_timeout"}
        assert diagnostics[1]["recorded_wait_ms"] >= 500
        assert diagnostics[1]["wait_hint"] and diagnostics[1]["replay_hint"]
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
            if viewer_browser is not None:
                await viewer_browser.close()
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
                variables={ACTION_VARIABLE: "PED-2002"},
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
                variables={ACTION_VARIABLE: "PED-2002"},
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


async def run_ai_observer_fallback_regression() -> None:
    from backend.services.ai_observer import analyze_recorded_action_with_ai

    previous_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        review = await analyze_recorded_action_with_ai(
            {
                "nome_amigavel": "Consulta genérica",
                "url_inicial": "https://sistema.exemplo.local/pedidos",
                "passos_playwright": [
                    {"tipo": "preencher", "seletor": "#codigo", "variavel": "codigo_pedido"},
                    {"tipo": "clicar", "seletor": "#buscar"},
                    {"tipo": "extrair_texto", "seletor": "#status", "nome": "status_pedido"},
                ],
            }
        )
        assert review["ai_reviewed"] is False
        assert review["ai_observer_summary"] == "IA não configurada; ação salva com análise local básica."
        assert len(review["waits"]) == 3
        assert review["variable_schema"][0]["key"] == "codigo_pedido"
        assert review["extraction_target"] == "status_pedido"
        print("Regressao: observador sem OPENAI_API_KEY usou analise local sem impedir o salvamento.")
    finally:
        if previous_key is not None:
            os.environ["OPENAI_API_KEY"] = previous_key


async def main(
    *,
    cycle_count: int = 3,
    include_revalidation: bool = True,
    replace_live_page: bool = False,
    emulate_devtools_live_view: bool = False,
) -> None:
    ui_map_existed = UI_MAP.exists()
    runs_existed = RUNS.exists()
    ui_map_backup = UI_MAP.read_bytes() if ui_map_existed else b""
    runs_backup = RUNS.read_bytes() if runs_existed else b""
    mapping_existed = MAPPING_EVIDENCE.exists()
    mapping_backup = MAPPING_EVIDENCE.read_bytes() if mapping_existed else b""
    run_evidence_before = set((ROOT / "data" / "runs").glob("*.png"))
    try:
        await run_ai_observer_fallback_regression()
        for cycle in range(1, cycle_count + 1):
            await run_cycle(
                cycle,
                replace_live_page=replace_live_page,
                emulate_devtools_live_view=emulate_devtools_live_view,
            )
        if include_revalidation:
            await run_revalidation_regression()
        print(f"Demo v0.1 validada em {cycle_count} ciclo(s) sem sistema externo.")
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
