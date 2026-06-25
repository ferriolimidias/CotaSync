from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest
from backend.services.action_pages import (
    ActionPageError,
    REAUTHENTICATION_MESSAGE,
    expected_action_hosts,
    select_desktop_page_for_action,
)
from backend.services.action_runner import run_action_sync


TARGET_URL = "https://nwcweb.randonconsorcios.com.br/CONCP/frmConCpRelResultadoAssembleia.aspx"


def desktop_action() -> ActionDetail:
    return ActionDetail(
        id="teste2",
        key="Teste2",
        name="Teste2",
        description="Abre a tela solicitada.",
        variables=[],
        steps_count=1,
        has_url=True,
        browser_mode="desktop_browser",
        url_inicial=TARGET_URL,
        ai_result_summary_enabled=False,
    )


class FakePage:
    def __init__(self, url: str, *, redirect_to: str = "") -> None:
        self.url = url
        self.redirect_to = redirect_to
        self.goto_calls: list[str] = []

    def is_closed(self) -> bool:
        return False

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.goto_calls.append(url)
        self.url = self.redirect_to or url

    async def wait_for_load_state(self, *_args: object, **_kwargs: object) -> None:
        return None


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    async def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.pages.append(page)
        return page


class DesktopActionPageTests(unittest.TestCase):
    def test_expected_hosts_include_initial_and_login_redirect_target(self) -> None:
        action = desktop_action().model_copy(
            update={
                "external_login_url": (
                    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
                    "?redirect_uri=https%3A%2F%2Fnwcweb.randonconsorcios.com.br%2Flogin-callback"
                )
            }
        )
        self.assertEqual(expected_action_hosts(action), {"nwcweb.randonconsorcios.com.br"})

    def test_google_page_is_navigated_to_initial_url_before_replay(self) -> None:
        google = FakePage("https://www.google.com/")
        selected = asyncio.run(
            select_desktop_page_for_action(desktop_action(), FakeContext([google]), google)
        )
        self.assertIs(selected, google)
        self.assertEqual(google.goto_calls, [TARGET_URL])
        self.assertEqual(google.url, TARGET_URL)

    def test_microsoft_redirect_requires_manual_reauthentication(self) -> None:
        google = FakePage(
            "https://www.google.com/",
            redirect_to="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        )
        with self.assertRaises(ActionPageError) as caught:
            asyncio.run(select_desktop_page_for_action(desktop_action(), FakeContext([google]), google))
        self.assertEqual(str(caught.exception), REAUTHENTICATION_MESSAGE)

    def test_microsoft_365_redirect_requires_manual_reauthentication(self) -> None:
        page = FakePage(
            "https://www.google.com/",
            redirect_to="https://m365.cloud.microsoft/?auth=2",
        )
        with self.assertRaises(ActionPageError) as caught:
            asyncio.run(select_desktop_page_for_action(desktop_action(), FakeContext([page]), page))
        self.assertEqual(str(caught.exception), REAUTHENTICATION_MESSAGE)


class DesktopActionRunTests(unittest.TestCase):
    def _run_with_final_url(self, final_url: str):
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Pagina", "url": final_url},
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner.executar_acao_fast_track",
            new=AsyncMock(return_value=execution),
        ):
            return asyncio.run(run_action_sync(desktop_action(), ActionRunRequest()))

    def test_desktop_action_never_succeeds_with_google_final_page(self) -> None:
        run = self._run_with_final_url("https://www.google.com/")
        self.assertEqual(run.status, "error")
        self.assertNotIn("sucesso", (run.operational_summary or "").casefold())
        self.assertIn("diagnósticos=1", run.technical_summary or "")

    def test_desktop_action_final_wrong_host_is_error(self) -> None:
        run = self._run_with_final_url("about:blank")
        self.assertEqual(run.status, "error")
        self.assertIn("página do sistema esperado", run.operational_summary or "")

    def test_run_endpoint_persists_new_run_visible_in_runs_api(self) -> None:
        action = desktop_action().model_copy(
            update={"browser_mode": "browserless", "url_inicial": None, "has_url": False}
        )
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Demo", "url": "http://demo.local/resultado"},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "backend.services.runs_repository.default_runs_path",
            return_value=Path(tmp) / "runs.json",
        ), patch("backend.api.runs.find_action", return_value=action), patch(
            "backend.services.action_runner.executar_acao_fast_track",
            new=AsyncMock(return_value=execution),
        ):
            client = TestClient(app)
            response = client.post("/api/actions/teste2/run", json={"variables": {}})
            self.assertEqual(response.status_code, 200)
            created = response.json()["run"]
            listed = client.get("/api/runs").json()["runs"]
        self.assertTrue(any(item["id"] == created["id"] for item in listed))

    def test_step_timeout_error_keeps_step_diagnostics_in_result_payload(self) -> None:
        diagnostic = {
            "step_diagnostics": [
                {
                    "step_index": 2,
                    "action_type": "clicar",
                    "target_label": "Elemento da rotina",
                    "wait_strategy": "expected_selector_after",
                    "waited_ms": 30000,
                    "result": "timeout",
                    "current_url_host": "nwcweb.randonconsorcios.com.br",
                    "current_title": "Consulta",
                }
            ],
            "retryable": True,
        }
        error = RuntimeError("timeout esperando expected_selector_after")
        error.diagnostics = diagnostic  # type: ignore[attr-defined]
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner.executar_acao_fast_track",
            new=AsyncMock(side_effect=error),
        ):
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest(variables={"grupo": "123"})))
        self.assertEqual(run.status, "error")
        self.assertEqual(run.result_payload["step_diagnostics"][0]["result"], "timeout")  # type: ignore[index]
        self.assertTrue(run.result_payload["retryable"])  # type: ignore[index]
        self.assertIn("demorou para abrir a próxima tela", run.operational_summary or "")


if __name__ == "__main__":
    unittest.main()
