from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.getenv("COTASYNC_REACT_BASE_URL", "http://127.0.0.1:3300")
ADMIN_USER = os.getenv("COTASYNC_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("COTASYNC_ADMIN_PASSWORD", "admin-test-password")
SESSION_COOKIE = os.getenv("COTASYNC_E2E_SESSION_COOKIE", "")
CSRF_COOKIE = os.getenv("COTASYNC_E2E_CSRF_COOKIE", "")
LEGACY_OPERATIONAL_PREFIXES = (
    "/api/clients",
    "/api/actions",
    "/api/batches",
    "/api/browser",
    "/api/demo",
    "/api/runs",
)


def test_react_operational_smoke() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768}, ignore_https_errors=True)
        console_errors: list[str] = []
        failed_requests: list[str] = []
        legacy_requests: list[str] = []

        def capture_console(message) -> None:
            text = message.text
            location = message.location.get("url", "")
            if "package.json" in text or (
                "desktop-cotasync.ferriolimidias.com.br" in location
                and "404 (File not found)" in text
            ):
                return
            if message.type in {"error"}:
                console_errors.append(text)

        page.on("console", capture_console)
        page.on("pageerror", lambda error: console_errors.append(str(error)))

        def capture_response(response) -> None:
            url = response.url
            path = urlparse(url).path
            if (
                response.status == 404
                and "desktop-cotasync.ferriolimidias.com.br" in url
                and path == "/package.json"
            ):
                return
            if response.status >= 400 and "/api/v1/auth/me" not in url:
                failed_requests.append(f"{response.status} {url}")
            if any(path.startswith(prefix) for prefix in LEGACY_OPERATIONAL_PREFIXES):
                legacy_requests.append(url)

        page.on("response", capture_response)
        if SESSION_COOKIE:
            parsed_base = urlparse(BASE_URL)
            page.context.add_cookies(
                [
                    {
                        "name": "cotasync_session",
                        "value": SESSION_COOKIE,
                        "domain": parsed_base.hostname or "127.0.0.1",
                        "path": "/",
                        "httpOnly": True,
                        "secure": parsed_base.scheme == "https",
                        "sameSite": "Lax",
                    },
                    {
                        "name": "cotasync_csrf",
                        "value": CSRF_COOKIE or "e2e-csrf",
                        "domain": parsed_base.hostname or "127.0.0.1",
                        "path": "/",
                        "httpOnly": False,
                        "secure": parsed_base.scheme == "https",
                        "sameSite": "Lax",
                    },
                ]
            )
        page.goto(BASE_URL, wait_until="networkidle")

        if not SESSION_COOKIE:
            page.get_by_label("Usuário").fill(ADMIN_USER)
            page.get_by_label("Senha").fill(ADMIN_PASSWORD)
            page.get_by_role("button", name="Entrar").click()
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible(timeout=10_000)

        headings = {
            "Clientes": "Clientes",
            "Ações": "Ações",
            "Ensinar ação": "Ensinar ação",
            "Execução em massa": "Execução",
            "Relatórios": "Relatórios",
            "Configurações": "Configurações",
            "Agendamentos": "Agendamentos",
            "Diagnóstico técnico": "Diagnóstico técnico",
        }
        for label, heading in headings.items():
            page.get_by_role("link", name=label, exact=True).click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(timeout=10_000)

        page.get_by_role("link", name="Configurações", exact=True).click()
        page.wait_for_load_state("networkidle")
        page.get_by_role("link", name="Abrir navegador", exact=True).click()
        page.wait_for_load_state("networkidle")
        expect(page.locator("aside")).to_have_count(0)
        expect(page.get_by_text("Conta", exact=True)).to_have_count(0)
        expect(page.get_by_text("Sistema externo", exact=True)).to_have_count(0)
        page.get_by_role("button", name=re.compile(r"^(Abrir navegador|Renovar acesso)$")).click()
        frame = page.locator('iframe[title="Navegador CotaSync"]')
        expect(frame).to_be_visible(timeout=15_000)
        page.wait_for_timeout(3_000)
        workspace = page.frame_locator('iframe[title="Navegador CotaSync"]').locator("body")
        expect(workspace).not_to_contain_text("401 Authorization Required")
        expect(workspace).not_to_contain_text("403")
        expect(workspace).not_to_contain_text("502")
        expect(workspace).not_to_contain_text("nginx error")
        page.get_by_role("link", name="Voltar", exact=True).click()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name="Configurações", exact=True)).to_be_visible(
            timeout=10_000
        )

        page.get_by_role("link", name="Clientes", exact=True).click()
        page.get_by_role("button", name="Importar CSV").click()
        with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", delete=False) as handle:
            handle.write(
                "id,name,group,active,grupo,cota,versao,notes\n"
                "e2e-preview-only,Smoke CSV React E2E,Homologacao,false,935,110,00,preview\n"
            )
            csv_path = Path(handle.name)
        page.locator('input[type="file"]').set_input_files(str(csv_path))
        page.get_by_role("button", name="Gerar preview").click()
        expect(page.get_by_text("Smoke CSV React E2E")).to_be_visible(timeout=10_000)
        expect(page.get_by_role("button", name="Confirmar importação")).to_be_enabled()
        page.keyboard.press("Escape")

        page.get_by_role("link", name="Relatórios", exact=True).click()
        page.get_by_placeholder("Cliente").fill("Smoke")
        expect(page.get_by_role("button", name="Exportação CSV")).to_be_visible()

        page.get_by_role("link", name="Ensinar ação", exact=True).click()
        page.get_by_role("textbox", name="Quantidade de parcelas", exact=True).fill(
            "Homologação React E2E"
        )
        page.get_by_role("textbox", name="Consultar quantas parcelas o cliente já pagou.").fill(
            "Validar abertura do workspace do navegador."
        )
        page.get_by_role("textbox", name="A quantidade de parcelas pagas.", exact=True).fill(
            "Workspace aberto."
        )

        permanent_loading = page.get_by_text(re.compile(r"^(Carregando|Verificando)(?! sessão)"))
        expect(permanent_loading).to_have_count(0, timeout=10_000)

        browser.close()
        assert not legacy_requests, f"Requests operacionais legados encontrados: {legacy_requests}"
        assert not failed_requests, f"Requests HTTP >= 400 inesperados: {failed_requests}"
        assert not console_errors, f"Erros de console encontrados: {console_errors}"


if __name__ == "__main__":
    test_react_operational_smoke()
    print("react-e2e-smoke-ok")
