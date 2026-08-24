from __future__ import annotations

import os
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.getenv("COTASYNC_REACT_BASE_URL", "http://127.0.0.1:3300")
ADMIN_USER = os.getenv("COTASYNC_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("COTASYNC_ADMIN_PASSWORD", "admin-test-password")


def test_react_operational_smoke() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(BASE_URL, wait_until="networkidle")

        page.get_by_label("Usuário").fill(ADMIN_USER)
        page.get_by_label("Senha").fill(ADMIN_PASSWORD)
        page.get_by_role("button", name="Entrar").click()
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible(timeout=10_000)

        headings = {
            "Clientes": "Clientes",
            "Ações": "Ações",
            "Execução em massa": "Execução",
            "Relatórios": "Relatórios",
            "Configurações": "Configurações",
        }
        for label, heading in headings.items():
            page.get_by_role("link", name=label, exact=True).click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading", name=heading)).to_be_visible(timeout=10_000)

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

        page.get_by_role("link", name="Diagnóstico técnico", exact=True).click()
        expect(page.get_by_text("Worker", exact=True).first).to_be_visible(timeout=10_000)

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
        page.get_by_role("button", name="Começar ensino").click()
        expect(page.get_by_text("Gravando")).to_be_visible(timeout=15_000)
        page.get_by_role("button", name="Abrir navegador").click()
        expect(page.frame_locator('iframe[title="Navegador CotaSync"]').locator("body")).to_be_attached(
            timeout=15_000
        )

        browser.close()


if __name__ == "__main__":
    test_react_operational_smoke()
    print("react-e2e-smoke-ok")
