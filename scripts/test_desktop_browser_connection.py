"""Smoke/integration test do Desktop Browser sem credenciais externas reais."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import async_playwright

from backend.services.browser_providers import DesktopBrowserProvider, desktop_view_url


API_BASE = os.getenv("COTASYNC_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
ACTION_NAME = "Desktop Browser MVP - consulta local"
ACTION_VARIABLE = "pedido_desktop"
EXTERNAL_SESSIONS = ROOT / "data" / "external_systems" / "sessions"
TRACKED_FILES = (
    ROOT / "data" / "browser_config.json",
    ROOT / "data" / "external_systems" / "current.json",
    ROOT / "data" / "ui_map.json",
    ROOT / "data" / "runs" / "runs.json",
)
_SESSION = requests.Session()
_CSRF_TOKEN = ""


def authenticate() -> None:
    global _CSRF_TOKEN
    username = os.getenv("COTASYNC_ADMIN_USERNAME", "admin")
    password = os.getenv("COTASYNC_ADMIN_PASSWORD", "")
    if not password:
        raise AssertionError("COTASYNC_ADMIN_PASSWORD precisa estar definido para o smoke test autenticado.")
    response = _SESSION.post(
        f"{API_BASE}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if not response.ok:
        raise AssertionError(f"POST /api/v1/auth/login retornou {response.status_code}: {response.text}")
    body = response.json()
    csrf_token = str(body.get("csrf_token") or "")
    if not csrf_token:
        raise AssertionError("Login autenticado nao retornou csrf_token.")
    _CSRF_TOKEN = csrf_token


def api(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 45) -> dict[str, Any]:
    headers = {"X-CSRF-Token": _CSRF_TOKEN} if method.upper() not in {"GET", "HEAD", "OPTIONS"} else None
    response = _SESSION.request(method, f"{API_BASE}{path}", json=payload, headers=headers, timeout=timeout)
    if not response.ok:
        raise AssertionError(f"{method} {path} retornou {response.status_code}: {response.text}")
    body = response.json()
    assert isinstance(body, dict)
    return body


async def clear_local_demo_cookie_and_check_cdp() -> None:
    playwright = await async_playwright().start()
    try:
        connection = await DesktopBrowserProvider().connect(playwright, "desktop-worker-smoke")
        await connection.context.clear_cookies(name="cotasync_demo_session")
        await connection.page.goto("about:blank")
        assert connection.page.url == "about:blank"
    finally:
        # Nao chama browser.close(): o Chromium desktop deve continuar rodando.
        await playwright.stop()


async def navigate_desktop_page(url: str) -> None:
    playwright = await async_playwright().start()
    try:
        connection = await DesktopBrowserProvider().connect(playwright, "desktop-manual-confirmation")
        await connection.page.goto(url, wait_until="domcontentloaded")
        assert connection.page.url == url
        assert await connection.page.title() == "Intranet Newcon"
    finally:
        await playwright.stop()


async def main() -> None:
    backups = {path: path.read_bytes() if path.is_file() else None for path in TRACKED_FILES}
    evidence_before = set((ROOT / "data").glob("mapeamento_*.png")) | set(
        (ROOT / "data" / "runs").glob("*.png")
    )
    session_id = ""
    manual_session_id = ""
    try:
        authenticate()
        await clear_local_demo_cookie_and_check_cdp()

        internal_view = os.getenv(
            "DESKTOP_BROWSER_INTERNAL_VIEW_URL",
            "http://cotasync_test_desktop_browser:6080/vnc.html",
        )
        view_response = requests.get(internal_view, timeout=5)
        assert view_response.ok and "noVNC" in view_response.text
        assert desktop_view_url().startswith("http://127.0.0.1:3200")

        configured = api("PUT", "/api/browser/config", {"browser_mode": "desktop_browser"})["browser"]
        assert configured["browser_mode"] == "desktop_browser"
        assert configured["desktop_browser"]["running"] is True
        assert configured["desktop_browser"]["cdp_reachable"] is True

        manual_config = api(
            "PUT",
            "/api/external-systems/current",
            {
                "external_system_name": "Sistema Externo Manual Teste",
                "external_login_url": "http://cotasync_test_backend:8000/demo/alvo",
                "validation": "manual_confirmation",
                # Comprovacao da precedencia do modo manual sobre sinais automaticos.
                "auth_success_text": "texto-que-nao-existe",
                "auth_success_selector": "#seletor-que-nao-existe",
            },
        )["external_system"]
        assert manual_config["validation"] == "manual_confirmation"

        manual_session = api("POST", "/api/demo/sessions")["session"]
        manual_session_id = str(manual_session["id"])
        session_id = manual_session_id
        assert manual_session["browser_mode"] == "desktop_browser"
        assert manual_session["using_external_system"] is True
        assert manual_session["auth_validation_mode"] == "manual_confirmation"
        assert manual_session["profile_reference"]

        await navigate_desktop_page(
            "http://cotasync_test_backend:8000/demo/manual-confirmation-test"
        )
        available = api("GET", f"/api/demo/sessions/{manual_session_id}")["session"]
        assert available["page_title"] == "Intranet Newcon"
        assert available["page_url"].endswith("/demo/manual-confirmation-test")

        manual_confirmed = api(
            "POST", f"/api/demo/sessions/{manual_session_id}/confirm-login"
        )["session"]
        assert manual_confirmed["status"] == "autenticada"
        assert manual_confirmed["manual_confirmed"] is True
        assert manual_confirmed["storage_state_saved"] is True
        assert manual_confirmed["confirmed_page_title"] == "Intranet Newcon"
        assert manual_confirmed["confirmed_page_url"].endswith("/demo/manual-confirmation-test")

        manual_recording = api(
            "POST", f"/api/demo/sessions/{manual_session_id}/recording/start"
        )["session"]
        assert manual_recording["status"] == "gravando"
        api("DELETE", f"/api/demo/sessions/{manual_session_id}")
        session_id = ""

        api(
            "PUT",
            "/api/external-systems/current",
            {
                "external_system_name": "",
                "external_login_url": "",
                "auth_success_text": "",
                "auth_success_selector": "",
            },
        )
        session = api("POST", "/api/demo/sessions")["session"]
        session_id = str(session["id"])
        assert session["browser_mode"] == "desktop_browser"
        assert session["live_url"] == desktop_view_url()
        assert session["page_url"].endswith("/demo/alvo")
        assert "Login" in session["page_title"]

        api(
            "POST",
            f"/api/demo/sessions/{session_id}/operator/fill",
            {"selector": "#demo-user", "value": "demo", "record_action": False},
        )
        api(
            "POST",
            f"/api/demo/sessions/{session_id}/operator/fill",
            {"selector": "#demo-password", "value": "demo", "record_action": False},
        )
        api(
            "POST",
            f"/api/demo/sessions/{session_id}/operator/click",
            {"selector": "#demo-login", "record_action": False},
        )
        confirmed = api("POST", f"/api/demo/sessions/{session_id}/confirm-login")["session"]
        assert confirmed["status"] == "autenticada"
        assert "Consulta" in confirmed["page_title"]

        api("POST", f"/api/demo/sessions/{session_id}/recording/start")
        filled = api(
            "POST",
            f"/api/demo/sessions/{session_id}/operator/fill",
            {"selector": "#pedido-codigo", "value": "PED-1001", "record_action": True},
        )["operator"]
        clicked = api(
            "POST",
            f"/api/demo/sessions/{session_id}/operator/click",
            {"selector": "#buscar-pedido", "record_action": True},
        )["operator"]
        assert filled["recorded"] is True and clicked["recorded"] is True

        stopped = api("POST", f"/api/demo/sessions/{session_id}/recording/stop")
        steps = stopped["steps"]
        assert [step["tipo"] for step in steps] == ["preencher", "clicar", "extrair_texto"]
        fill_index = next(step["index"] for step in steps if step["tipo"] == "preencher")
        saved = api(
            "POST",
            f"/api/demo/sessions/{session_id}/actions",
            {
                "name": ACTION_NAME,
                "description": "Validacao local do worker desktop persistente.",
                "variable_names": {str(fill_index): ACTION_VARIABLE},
            },
            timeout=60,
        )["action"]
        assert saved["learning_mode"] == "desktop_browser_mechanical_ai_reviewed"

        replay = api(
            "POST",
            f"/api/actions/{saved['id']}/run",
            {
                "variables": {ACTION_VARIABLE: "PED-2002"},
                "mode": "sync",
                "requested_by": "desktop-browser-smoke",
            },
            timeout=60,
        )["run"]
        assert replay["status"] == "success", replay
        assert replay["result_payload"]["dados_extraidos"]["status_pedido"] == "Enviado"
        print(f"run_id={replay['id']}")
        print(f"runner={replay.get('result_payload', {}).get('runner')}")
        print(f"whether_desktop_browser_used={replay.get('result_payload', {}).get('whether_desktop_browser_used')}")
        print(f"status={replay['status']}")
        print("resultado=status_pedido:Enviado")

        health = api("GET", "/api/health/desktop-browser")
        assert health["status"] == "ok" and health["cdp_reachable"] is True
        print(
            "Desktop Browser: CDP, noVNC, alvo local, operador fill/click, aprendizado e replay validados."
        )
    finally:
        if session_id:
            try:
                api("DELETE", f"/api/demo/sessions/{session_id}")
            except Exception:
                pass
        if manual_session_id:
            for session_dir in EXTERNAL_SESSIONS.glob(f"*/{manual_session_id}"):
                shutil.rmtree(session_dir, ignore_errors=True)
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


if __name__ == "__main__":
    asyncio.run(main())
