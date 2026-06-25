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
from backend.services.session_guardian import SessionGuardian, SessionGuardianConfig


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


class FakeGuardianLocator:
    def __init__(self, page: "FakeGuardianPage", selector: str = "", text: str = "") -> None:
        self.page = page
        self.selector = selector
        self.text = text

    @property
    def first(self) -> "FakeGuardianLocator":
        return self

    def filter(self, *, has_text: object = None, **_kwargs: object) -> "FakeGuardianLocator":
        text = getattr(has_text, "pattern", has_text)
        return FakeGuardianLocator(self.page, self.selector, str(text or ""))

    async def inner_text(self, **_kwargs: object) -> str:
        return self.page.body_text

    async def count(self) -> int:
        if self.selector == "body":
            return 1
        if self.selector == "input[type='password']:visible":
            return 1 if self.page.password_visible else 0
        if self.text:
            return 1 if self.page.has_visible_text(self.text) else 0
        return 0

    async def is_visible(self) -> bool:
        return await self.count() > 0

    async def click(self, **_kwargs: object) -> None:
        self.page.clicked_texts.append(self.text)
        if self.page.click_redirect_url:
            self.page.url = self.page.click_redirect_url
            self.page.body_text = self.page.redirect_body_text


class FakeGuardianPage:
    def __init__(
        self,
        url: str,
        body_text: str,
        *,
        title: str = "",
        ready_state: str = "complete",
        password_visible: bool = False,
        click_redirect_url: str = "",
        redirect_body_text: str = "",
    ) -> None:
        self.url = url
        self.body_text = body_text
        self.title_text = title
        self.ready_state = ready_state
        self.password_visible = password_visible
        self.click_redirect_url = click_redirect_url
        self.redirect_body_text = redirect_body_text
        self.clicked_texts: list[str] = []
        self.reload_calls = 0

    async def title(self) -> str:
        return self.title_text

    async def evaluate(self, _script: str) -> str:
        return self.ready_state

    def locator(self, selector: str) -> FakeGuardianLocator:
        return FakeGuardianLocator(self, selector)

    def get_by_text(self, text: str, **_kwargs: object) -> FakeGuardianLocator:
        return FakeGuardianLocator(self, text=str(text))

    async def reload(self, **_kwargs: object) -> None:
        self.reload_calls += 1
        self.ready_state = "complete"
        self.body_text = "Consulta de Pedidos"

    async def wait_for_load_state(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def wait_for_timeout(self, _timeout: int) -> None:
        return None

    def has_visible_text(self, text: str) -> bool:
        return str(text or "").casefold() in self.body_text.casefold()


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


class SessionGuardianTests(unittest.TestCase):
    def _guardian(self) -> SessionGuardian:
        return SessionGuardian(
            SessionGuardianConfig(
                check_timeout_seconds=1,
                recovery_attempts=2,
                refresh_attempts=1,
                recovery_backoff_seconds=1,
            )
        )

    def test_classifies_authenticated_system_page(self) -> None:
        page = FakeGuardianPage(TARGET_URL, "Intranet Newcon")
        state = asyncio.run(
            self._guardian().classify(page, desktop_action().model_dump(), authenticated=True)
        )
        self.assertEqual(state.state, "authenticated_system")

    def test_classifies_microsoft_pick_account_page(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nPriscila Susin\nD0004267@rdmz.com.br",
            title="Sign in",
        )
        state = asyncio.run(self._guardian().classify(page, desktop_action().model_dump()))
        self.assertEqual(state.state, "microsoft_pick_account")

    def test_clicks_configured_saved_account_only_when_visible(self) -> None:
        action = desktop_action().model_dump()
        action["microsoft_saved_account_text"] = "Priscila Susin"
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nPriscila Susin",
            click_redirect_url=TARGET_URL,
            redirect_body_text="Intranet Newcon",
        )
        clicked = asyncio.run(self._guardian().click_configured_saved_account(page, action))
        self.assertTrue(clicked)
        self.assertIn("Priscila Susin", page.clicked_texts)

    def test_does_not_click_random_saved_account_without_match(self) -> None:
        action = desktop_action().model_dump()
        action["microsoft_saved_account_text"] = "Priscila Susin"
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nOutra Pessoa",
        )
        clicked = asyncio.run(self._guardian().click_configured_saved_account(page, action))
        self.assertFalse(clicked)
        self.assertEqual(page.clicked_texts, [])

    def test_password_mfa_and_consent_require_manual_intervention(self) -> None:
        samples = [
            ("Enter password", "microsoft_password_required"),
            ("Verify your identity with Microsoft Authenticator", "microsoft_mfa_required"),
            ("Permissions requested by this app", "microsoft_consent_required"),
        ]
        for body, expected in samples:
            page = FakeGuardianPage(
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                body,
                password_visible=expected == "microsoft_password_required",
            )
            state = asyncio.run(self._guardian().classify(page, desktop_action().model_dump()))
            self.assertEqual(state.state, expected)
            self.assertTrue(state.operator_action_required)

    def test_recovery_refreshes_and_continues_when_session_recovers(self) -> None:
        page = FakeGuardianPage(TARGET_URL, "Carregando", ready_state="interactive")
        calls = 0

        async def is_authenticated(_page: object) -> bool:
            nonlocal calls
            calls += 1
            return page.reload_calls > 0

        result = asyncio.run(
            self._guardian().ensure_authenticated(
                page,
                desktop_action().model_dump(),
                is_authenticated=is_authenticated,
                checkpoint="before_step_auth_check",
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(page.reload_calls, 1)
        self.assertTrue(result.recovery_attempted)


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

    def test_session_checkpoint_diagnostics_persist_in_error_payload(self) -> None:
        diagnostic = {
            "session_state": "microsoft_mfa_required",
            "operator_action_required": True,
            "recovery_attempts": 1,
            "recovery_steps": [{"checkpoint": "before_action_auth_check", "result": "manual_intervention_required"}],
            "checkpoint_diagnostics": [
                {
                    "checkpoint": "before_action_auth_check",
                    "session_state": "microsoft_mfa_required",
                    "result": "failed",
                }
            ],
            "retryable": False,
        }
        error = RuntimeError("Não consegui continuar porque a Microsoft solicitou senha ou MFA.")
        error.diagnostics = diagnostic  # type: ignore[attr-defined]
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner.executar_acao_fast_track",
            new=AsyncMock(side_effect=error),
        ):
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest()))
        self.assertEqual(run.status, "error")
        self.assertEqual(run.result_payload["session_state"], "microsoft_mfa_required")  # type: ignore[index]
        self.assertTrue(run.result_payload["operator_action_required"])  # type: ignore[index]
        self.assertEqual(run.result_payload["checkpoint_diagnostics"][0]["result"], "failed")  # type: ignore[index]
        self.assertIn("Microsoft solicitou senha ou MFA", run.operational_summary or "")


if __name__ == "__main__":
    unittest.main()
