from __future__ import annotations

import tests  # noqa: F401

import asyncio
import json
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
from backend.services.action_runner import finish_action_run, run_action_sync, start_action_run
from backend.db import Action as DbAction, ActionVersion, SessionLocal
from backend.services.actions_repository import load_actions_catalog, save_learned_action
from backend.services.file_names import safe_file_name
from backend.services.result_selection import extract_with_contract
from backend.services.runs_repository import get_run
from backend.services.session_guardian import SessionGuardian, SessionGuardianConfig
from backend.motor_browser import (
    is_learned_client_query_transition,
    query_result_matches_inputs,
    verify_postcondition,
)
from tests.auth_helpers import authenticated_client


TARGET_URL = "https://nwcweb.randonconsorcios.com.br/CONCP/frmConCpRelResultadoAssembleia.aspx"


def saved_action_definition(action_key: str) -> dict:
    with SessionLocal() as session:
        db_action = session.query(DbAction).filter(DbAction.key == action_key).first()
        version = session.get(ActionVersion, db_action.published_version_id) if db_action and db_action.published_version_id else None
        return dict(version.definition or {}) if version is not None else {}


class VisualResultSelectionTests(unittest.TestCase):
    def test_confirm_visual_contract_preserves_mechanical_map_and_generates_summary(self) -> None:
        raw_action = {
            "nome_amigavel": "Porcentagem a pagar",
            "browser_mode": "desktop_browser",
            "url_inicial": TARGET_URL,
            "passos_playwright": [{"tipo": "clicar", "seletor": "#consultar"}],
            "robust_steps": [{"tipo": "clicar", "seletor": "#consultar", "elapsed_ms": 10}],
            "learning_events": [{"step_index": 0, "event_type": "click", "selector": "#consultar"}],
            "variable_schema": [{"key": "grupo", "label": "Grupo", "required": True}],
            "reviewed_overlay": {"waits": [{"after_step_index": 0, "strategy": "dom_stable"}]},
            "extraction_review": {},
            "extraction_targets": ["% Pagar"],
        }
        save_learned_action("Porcentagem", raw_action)
        with authenticated_client() as client:
            response = client.post(
                "/api/actions/porcentagem/result-selection/confirm",
                json={
                    "target_name": "porcentagem a pagar",
                    "screen_label": "% Pagar",
                    "selection_type": "table_footer_total",
                    "candidate": {
                        "label": "% Pagar",
                        "value": "0,0000",
                        "type": "table_footer_total",
                        "table_headers": ["Valor Pagar", "Ocorrência", "% Pagar"],
                        "row_context": "Total | % Pagar | 0,0000",
                    },
                },
            )
        saved = saved_action_definition("Porcentagem")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["passos_playwright"], raw_action["passos_playwright"])
        self.assertEqual(saved["robust_steps"], raw_action["robust_steps"])
        self.assertEqual(saved["learning_events"], raw_action["learning_events"])
        self.assertEqual(saved["variable_schema"], raw_action["variable_schema"])
        self.assertEqual(saved["extraction_review"]["selection_type"], "table_footer_total")
        self.assertEqual(saved["extraction_review"]["example_value"], "0,0000")
        self.assertIn("% Pagar", saved["final_summary_instruction"])

    def test_quick_execution_contract_priority_replaces_generic_ocorrencia_result(self) -> None:
        dom = """
        <table>
          <tr><th>Valor Pagar</th><th>Ocorrência</th><th>% Pagar</th></tr>
          <tr><td>6776,91</td><td>Percentual Ideal</td><td>77,4000</td></tr>
          <tr><td>Total</td><td>% Pagar</td><td>0,0000</td></tr>
        </table>
        """
        contract = {
            "target_name": "porcentagem a pagar",
            "screen_label": "% Pagar",
            "selection_type": "table_footer_total",
            "value_type": "decimal_percent",
            "avoid_labels": ["Ocorrência", "Valor Pagar"],
        }
        generic = {"porcentagem a pagar": "Ocorrência"}
        result = extract_with_contract(dom, "", contract)
        if result["value"]:
            generic[contract["target_name"]] = result["value"]

        self.assertEqual(generic["porcentagem a pagar"], "0,0000")

    def test_qtd_pcls_pagas_visual_contract_still_extracts_simple_field(self) -> None:
        result = extract_with_contract(
            "<table><tr><td>Qtd. Pcls. Pagas</td><td>038</td></tr></table>",
            "",
            {"target_name": "Qtd. Pcls. Pagas", "screen_label": "Qtd. Pcls. Pagas", "selection_type": "field_value", "value_type": "integer"},
        )

        self.assertEqual(result["value"], "038")
        self.assertFalse(result["needs_attention"])


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
        access_profile_name="Priscila",
        microsoft_saved_account_text="Priscila Susin",
        microsoft_saved_account_identifier="D0004267@rdmz.com.br",
        expected_system_host="nwcweb.randonconsorcios.com.br",
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


class FakeReplayLocator:
    @property
    def first(self) -> "FakeReplayLocator":
        return self

    def nth(self, _index: int) -> "FakeReplayLocator":
        return self

    async def wait_for(self, **_kwargs: object) -> None:
        return None

    async def count(self) -> int:
        return 1

    async def is_visible(self) -> bool:
        return True

    async def fill(self, _value: str, **_kwargs: object) -> None:
        raise RuntimeError("Campo indisponivel")


class FakeReplayPage:
    url = TARGET_URL

    def is_closed(self) -> bool:
        return False

    def locator(self, _selector: str) -> FakeReplayLocator:
        return FakeReplayLocator()

    async def title(self) -> str:
        return "Consulta"

    async def screenshot(self, **_kwargs: object) -> None:
        raise OSError("sem permissao")


class FakeReplayBrowser:
    contexts: list[object] = []

    async def new_context(self) -> "FakeReplayContext":
        return FakeReplayContext()

    async def close(self) -> None:
        return None


class FakeReplayContext:
    pages: list[FakeReplayPage] = []

    async def new_page(self) -> FakeReplayPage:
        return FakeReplayPage()


class FakeReplayChromium:
    async def connect_over_cdp(self, _url: str) -> FakeReplayBrowser:
        return FakeReplayBrowser()


class FakeAsyncPlaywright:
    chromium = FakeReplayChromium()

    async def __aenter__(self) -> "FakeAsyncPlaywright":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeReplayConnection:
    browser = FakeReplayBrowser()
    context = FakeReplayContext()
    page = FakeReplayPage()


class FakeReplayProvider:
    close_browser_on_session_end = False

    async def connect(self, _playwright: object, _session_id: str) -> FakeReplayConnection:
        return FakeReplayConnection()


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
        if self.selector in self.page.visible_selectors:
            return 1
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
        visible_selectors: set[str] | None = None,
    ) -> None:
        self.url = url
        self.body_text = body_text
        self.title_text = title
        self.ready_state = ready_state
        self.password_visible = password_visible
        self.click_redirect_url = click_redirect_url
        self.redirect_body_text = redirect_body_text
        self.visible_selectors = visible_selectors or set()
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

    def get_by_label(self, text: str, **_kwargs: object) -> FakeGuardianLocator:
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

    def test_expected_hosts_ignore_microsoft_url_saved_as_expected_system_host(self) -> None:
        action = desktop_action().model_copy(
            update={
                "expected_system_host": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?prompt=consent",
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

    def test_desktop_replay_navigates_to_complete_initial_url_before_step_zero(self) -> None:
        full_url = (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
            "client_id=abc&response_type=code&response_mode=query&scope=openid&"
            "redirect_uri=https%3A%2F%2Fnwcweb.randonconsorcios.com.br%2FfrmCorCCCnsLogin.aspx&"
            "state=XYZ&prompt=consent"
        )
        page = FakePage("https://www.google.com/")
        action = desktop_action().model_copy(
            update={
                "url_inicial": full_url,
                "external_login_url": full_url,
            }
        )
        with self.assertRaises(ActionPageError):
            asyncio.run(select_desktop_page_for_action(action, FakeContext([page]), page))
        self.assertEqual(page.goto_calls, [full_url])
        self.assertNotEqual(page.goto_calls[0], "https://m365.cloud.microsoft/search")

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

    def _stateful_action(self) -> dict[str, object]:
        return {
            "expected_system_host": "nwcweb.randonconsorcios.com.br",
            "robust_steps": [
                {"tipo": "clicar", "seletor": "#account", "expected_url_before": "https://login.microsoftonline.com/authorize"},
                {"tipo": "clicar", "seletor": "#idSIButton9", "expected_url_before": "https://login.microsoftonline.com/authorize"},
                {"tipo": "clicar", "seletor": "#ctl00_img_Atendimento", "expected_url_before": TARGET_URL},
                {"tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"},
                {"tipo": "preencher", "seletor": "#cota", "variavel": "cota"},
                {"tipo": "preencher", "seletor": "#versao", "variavel": "versao"},
                {"tipo": "clicar", "seletor": "#localizar", "expected_url_before": TARGET_URL},
                {"tipo": "extrair_texto", "seletor": "#resultado", "nome": "Resultado"},
            ],
            "extraction_review": {"selector_data": {"primary": "#resultado"}},
        }

    def test_observes_auth_continue_and_resumes_at_visible_transition(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/authorize",
            "Pick an account",
            visible_selectors={"#idSIButton9"},
        )
        observation = asyncio.run(self._guardian().observe_workflow_state(page, self._stateful_action()))
        plan = asyncio.run(self._guardian().plan_resume_index(page, self._stateful_action(), observation))
        self.assertEqual(observation["workflow_state"], "auth_continue")
        self.assertEqual(plan["resume_index"], 1)

    def test_observes_home_and_skips_microsoft_steps(self) -> None:
        page = FakeGuardianPage(TARGET_URL, "Intranet Newcon", visible_selectors={"#ctl00_img_Atendimento"})
        observation = asyncio.run(self._guardian().observe_workflow_state(page, self._stateful_action(), authenticated=True))
        plan = asyncio.run(self._guardian().plan_resume_index(page, self._stateful_action(), observation))
        self.assertEqual(observation["workflow_state"], "home_ready")
        self.assertEqual(plan["resume_index"], 2)

    def test_observes_consulta_and_result_resume_states(self) -> None:
        action = self._stateful_action()
        consulta = FakeGuardianPage(TARGET_URL, "Consulta", visible_selectors={"#grupo", "#cota", "#versao"})
        consulta_observation = asyncio.run(self._guardian().observe_workflow_state(consulta, action, authenticated=True))
        consulta_plan = asyncio.run(self._guardian().plan_resume_index(consulta, action, consulta_observation))
        self.assertEqual(consulta_observation["workflow_state"], "consulta_ready")
        self.assertEqual(consulta_plan["resume_index"], 3)

        result = FakeGuardianPage(TARGET_URL, "Resultado", visible_selectors={"#resultado", "#grupo", "#cota", "#versao"})
        result_observation = asyncio.run(self._guardian().observe_workflow_state(result, action, authenticated=True))
        result_plan = asyncio.run(self._guardian().plan_resume_index(result, action, result_observation))
        self.assertEqual(result_observation["workflow_state"], "result_ready")
        self.assertEqual(result_plan["resume_index"], 3)

    def test_result_without_consulta_transition_stops_safely(self) -> None:
        action = self._stateful_action()
        result = FakeGuardianPage(TARGET_URL, "Resultado", visible_selectors={"#resultado"})
        observation = asyncio.run(self._guardian().observe_workflow_state(result, action, authenticated=True))
        plan = asyncio.run(self._guardian().plan_resume_index(result, action, observation))
        self.assertEqual(observation["workflow_state"], "result_ready")
        self.assertIsNone(plan["resume_index"])
        self.assertEqual(plan["reason"], "result_to_consulta_transition_not_learned")

    def test_result_reenters_consulta_through_learned_non_microsoft_transition(self) -> None:
        action = self._stateful_action()
        result = FakeGuardianPage(TARGET_URL, "Resultado", visible_selectors={"#resultado", "#ctl00_img_Atendimento"})
        observation = asyncio.run(self._guardian().observe_workflow_state(result, action, authenticated=True))
        plan = asyncio.run(self._guardian().plan_resume_index(result, action, observation))
        self.assertEqual(observation["workflow_state"], "result_ready")
        self.assertEqual(plan["resume_index"], 2)
        self.assertEqual(plan["reentry_strategy"], "transition")
        self.assertEqual(plan["target_workflow_state"], "consulta_ready")

    def test_query_fingerprint_rejects_previous_client_even_when_result_is_equal(self) -> None:
        previous_page = "Cota: 000935 0110-00\nQtd. Pcls. Pagas: 034"
        current_client = {"grupo": "935", "cota": "112", "versao": "00"}
        self.assertFalse(query_result_matches_inputs(previous_page, current_client))

    def test_query_fingerprint_accepts_same_result_for_different_client_when_identity_matches(self) -> None:
        current_page = "Cota: 000935 0112-00\nQtd. Pcls. Pagas: 034"
        current_client = {"grupo": "935", "cota": "112", "versao": "00"}
        self.assertTrue(query_result_matches_inputs(current_page, current_client))

    def test_complex_action_marks_first_post_input_click_as_query_transition(self) -> None:
        steps = [
            {"tipo": "preencher", "variavel": "grupo"},
            {"tipo": "preencher", "variavel": "cota"},
            {"tipo": "clicar", "seletor": "#localizar"},
            {"tipo": "clicar", "seletor": "#formulario"},
        ]
        self.assertTrue(is_learned_client_query_transition(steps, 2, {"grupo", "cota"}, False))
        self.assertFalse(is_learned_client_query_transition(steps, 3, {"grupo", "cota"}, False))

    def test_simple_action_does_not_mark_terminal_result_click_as_complex_transition(self) -> None:
        steps = [
            {"tipo": "preencher", "variavel": "grupo"},
            {"tipo": "preencher", "variavel": "cota"},
            {"tipo": "clicar", "seletor": "#localizar"},
        ]
        self.assertFalse(is_learned_client_query_transition(steps, 2, {"grupo", "cota"}, False))

    def test_secret_and_unknown_states_stop_without_automation(self) -> None:
        action = self._stateful_action()
        password = FakeGuardianPage(
            "https://login.microsoftonline.com/authorize",
            "Enter password",
            password_visible=True,
        )
        password_observation = asyncio.run(self._guardian().observe_workflow_state(password, action))
        self.assertEqual(password_observation["workflow_state"], "auth_secret_required")

        unknown = FakeGuardianPage(TARGET_URL, "Tela desconhecida")
        unknown_observation = asyncio.run(self._guardian().observe_workflow_state(unknown, action, authenticated=True))
        self.assertEqual(unknown_observation["workflow_state"], "unknown")
        self.assertEqual(unknown_observation["reason"], "unknown_browser_state")

    def test_postcondition_failure_stops_transition(self) -> None:
        page = FakeGuardianPage(TARGET_URL, "Consulta", visible_selectors=set())
        with self.assertRaisesRegex(RuntimeError, "Pós-condição não alcançada"):
            asyncio.run(verify_postcondition(page, "#next", 3, timeout_ms=1))

    def test_m365_host_classifies_as_unknown_microsoft_auth_not_empty(self) -> None:
        page = FakeGuardianPage("https://m365.cloud.microsoft/", "", title="Microsoft 365")
        state = asyncio.run(self._guardian().classify(page, desktop_action().model_dump()))
        self.assertEqual(state.state, "unknown_microsoft_auth")
        self.assertEqual(state.current_host, "m365.cloud.microsoft")

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

    def test_recovery_does_not_click_configured_pick_account_without_learned_step(self) -> None:
        action = desktop_action().model_dump()
        page = FakeGuardianPage(
            "https://m365.cloud.microsoft/",
            "Pick an account\nPriscila Susin\nD0004267@rdmz.com.br",
            click_redirect_url=TARGET_URL,
            redirect_body_text="Intranet Newcon",
        )

        async def is_authenticated(_page: object) -> bool:
            return page.url == TARGET_URL

        result = asyncio.run(
            self._guardian().ensure_authenticated(
                page,
                action,
                is_authenticated=is_authenticated,
                checkpoint="before_action_auth_check",
            )
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.recovery_attempts, 1)
        self.assertEqual(result.recovery_steps[0]["action"], "monitor_microsoft_auth")
        self.assertEqual(result.recovery_steps[0]["result"], "manual_intervention_or_learned_step_required")
        self.assertEqual(page.clicked_texts, [])

    def test_pick_account_without_matching_profile_requires_operator_action(self) -> None:
        action = desktop_action().model_dump()
        action["microsoft_saved_account_text"] = "Priscila Susin"
        action["microsoft_saved_account_identifier"] = "D0004267@rdmz.com.br"
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nOutra Pessoa",
        )
        result = asyncio.run(
            self._guardian().ensure_authenticated(
                page,
                action,
                is_authenticated=AsyncMock(return_value=False),
                checkpoint="before_action_auth_check",
            )
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.recovery_attempts, 1)
        self.assertTrue(result.operator_action_required)
        self.assertEqual(result.recovery_steps[0]["result"], "manual_intervention_or_learned_step_required")

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

    def test_profile_name_alone_is_not_a_saved_account_match(self) -> None:
        action = desktop_action().model_dump()
        action["access_profile_name"] = "Priscila"
        action["microsoft_saved_account_text"] = "Priscila Susin"
        action["microsoft_saved_account_identifier"] = "D0004267@rdmz.com.br"
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nPriscila Outro Perfil\noutra@rdmz.com.br",
        )
        clicked = asyncio.run(self._guardian().click_configured_saved_account(page, action))
        self.assertFalse(clicked)
        self.assertEqual(page.clicked_texts, [])

    def test_recovery_requires_operator_when_only_profile_name_is_visible(self) -> None:
        action = desktop_action().model_dump()
        action["access_profile_name"] = "Priscila"
        action["microsoft_saved_account_text"] = "Priscila Susin"
        action["microsoft_saved_account_identifier"] = "D0004267@rdmz.com.br"
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nPriscila Outro Perfil\noutra@rdmz.com.br",
        )
        result = asyncio.run(
            self._guardian().ensure_authenticated(
                page,
                action,
                is_authenticated=AsyncMock(return_value=False),
                checkpoint="before_action_auth_check",
            )
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.operator_action_required)
        self.assertEqual(result.recovery_attempts, 1)
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

    def test_password_mfa_and_consent_recovery_requires_operator_action(self) -> None:
        for body in (
            "Enter password",
            "Verify your identity with Microsoft Authenticator",
            "Permissions requested by this app",
        ):
            page = FakeGuardianPage(
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                body,
                password_visible="password" in body.casefold(),
            )
            result = asyncio.run(
                self._guardian().ensure_authenticated(
                    page,
                    desktop_action().model_dump(),
                    is_authenticated=AsyncMock(return_value=False),
                )
            )
            self.assertFalse(result.ok)
            self.assertTrue(result.operator_action_required)
            self.assertEqual(result.recovery_attempts, 1)

    def test_learned_pick_account_click_is_compatible_without_fixed_profile(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Pick an account\nOutra Pessoa",
            visible_selectors={'div[aria-label="Sign in with outra@rdmz.com.br work or school account."]'},
        )
        diagnostic = asyncio.run(
            self._guardian().learned_microsoft_step_diagnostic(
                page,
                desktop_action().model_dump(),
                {
                    "tipo": "clicar",
                    "seletor": 'div[aria-label="Sign in with outra@rdmz.com.br work or school account."]',
                    "expected_url_before": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                },
            )
        )
        self.assertTrue(diagnostic["learned_microsoft_step_compatible"])
        self.assertFalse(diagnostic["operator_action_required"])
        self.assertTrue(diagnostic["whether_next_step_was_microsoft_click"])
        self.assertEqual(diagnostic["next_step_type"], "clicar")
        self.assertEqual(
            diagnostic["next_step_selector"],
            'div[aria-label="Sign in with outra@rdmz.com.br work or school account."]',
        )
        self.assertEqual(diagnostic["next_step_host_before"], "login.microsoftonline.com")

    def test_learned_accept_click_is_compatible_but_missing_accept_step_blocks(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Permissions requested by this app\nAccept",
            visible_selectors={'input[name="idSIButton9"]'},
        )
        compatible = asyncio.run(
            self._guardian().learned_microsoft_step_diagnostic(
                page,
                desktop_action().model_dump(),
                {
                    "tipo": "clicar",
                    "seletor": 'input[name="idSIButton9"]',
                    "target_text": "Accept",
                    "expected_url_before": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                },
            )
        )
        blocked = asyncio.run(
            self._guardian().learned_microsoft_step_diagnostic(
                page,
                desktop_action().model_dump(),
                {"tipo": "clicar", "seletor": "#ctl00_Conteudo_btnLocalizar"},
            )
        )
        self.assertTrue(compatible["learned_microsoft_step_compatible"])
        self.assertFalse(compatible["operator_action_required"])
        self.assertEqual(compatible["next_step_selector"], 'input[name="idSIButton9"]')
        self.assertEqual(compatible["next_step_url_before"], "https://login.microsoftonline.com/common/oauth2/v2.0/authorize")
        self.assertFalse(blocked["learned_microsoft_step_compatible"])
        self.assertTrue(blocked["operator_action_required"])
        self.assertEqual(blocked["reason"], "next_step_selector_not_visible_on_microsoft_page")

    def test_learned_accept_click_can_match_by_recorded_text_when_selector_changed(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Permissions requested by this app\nAccept",
            visible_selectors=set(),
        )
        diagnostic = asyncio.run(
            self._guardian().learned_microsoft_step_diagnostic(
                page,
                desktop_action().model_dump(),
                {
                    "tipo": "clicar",
                    "seletor": 'input[name="idSIButton9"]',
                    "target_text": "Accept",
                    "expected_url_before": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                },
            )
        )
        self.assertTrue(diagnostic["learned_microsoft_step_compatible"])
        self.assertEqual(diagnostic["matched_by"], "target_text")
        self.assertFalse(diagnostic["operator_action_required"])

    def test_microsoft_page_with_non_matching_next_step_host_blocks_with_diagnostic(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Permissions requested by this app\nAccept",
            visible_selectors={'input[name="idSIButton9"]'},
        )
        diagnostic = asyncio.run(
            self._guardian().learned_microsoft_step_diagnostic(
                page,
                desktop_action().model_dump(),
                {
                    "tipo": "clicar",
                    "seletor": 'input[name="idSIButton9"]',
                    "target_text": "Accept",
                    "expected_url_before": "https://nwcweb.randonconsorcios.com.br/frmMain.aspx",
                },
            )
        )
        self.assertFalse(diagnostic["learned_microsoft_step_compatible"])
        self.assertTrue(diagnostic["operator_action_required"])
        self.assertEqual(diagnostic["reason"], "next_step_expected_host_mismatch")
        self.assertEqual(diagnostic["next_step_type"], "clicar")
        self.assertEqual(diagnostic["next_step_selector"], 'input[name="idSIButton9"]')
        self.assertEqual(diagnostic["next_step_host_before"], "nwcweb.randonconsorcios.com.br")

    def test_blocking_diagnostic_includes_next_step_index_when_available(self) -> None:
        page = FakeGuardianPage(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "Permissions requested by this app\nAccept",
        )
        diagnostic = asyncio.run(
            self._guardian().learned_microsoft_step_diagnostic(
                page,
                desktop_action().model_dump(),
                {
                    "__cotasync_step_index": 2,
                    "tipo": "preencher",
                    "seletor": "#ctl00_Conteudo_edtGrupo",
                    "expected_url_before": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                },
            )
        )
        self.assertFalse(diagnostic["learned_microsoft_step_compatible"])
        self.assertTrue(diagnostic["operator_action_required"])
        self.assertEqual(diagnostic["reason"], "next_step_is_not_click")
        self.assertEqual(diagnostic["next_step_index"], 2)
        self.assertEqual(diagnostic["next_step_type"], "preencher")
        self.assertEqual(diagnostic["next_step_selector"], "#ctl00_Conteudo_edtGrupo")

    def test_password_and_mfa_never_become_learned_microsoft_clicks(self) -> None:
        for body, expected_state in (
            ("Enter password", "microsoft_password_required"),
            ("Verify your identity with Microsoft Authenticator", "microsoft_mfa_required"),
        ):
            page = FakeGuardianPage(
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                body,
                password_visible=expected_state == "microsoft_password_required",
                visible_selectors={"#idSIButton9"},
            )
            diagnostic = asyncio.run(
                self._guardian().learned_microsoft_step_diagnostic(
                    page,
                    desktop_action().model_dump(),
                    {"tipo": "clicar", "seletor": "#idSIButton9"},
                )
            )
            self.assertEqual(diagnostic["session_state"], expected_state)
            self.assertFalse(diagnostic["learned_microsoft_step_compatible"])
            self.assertTrue(diagnostic["operator_action_required"])

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


class AccessProfileCatalogTests(unittest.TestCase):
    def test_legacy_action_without_profile_is_marked_unconfigured_but_profile_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_path = Path(tmp) / "ui_map.json"
            catalog_path.write_text(
                '{"acoes_conhecidas":{"Legada":{"nome_amigavel":"Legada","passos_playwright":[{"tipo":"clicar","seletor":"#x"}]}}}',
                encoding="utf-8",
            )
            catalog = load_actions_catalog(catalog_path)
        action = catalog.actions[0]
        self.assertTrue(action.legacy_unconfigured)
        self.assertEqual(action.access_profile_name, "Priscila")
        self.assertEqual(action.microsoft_saved_account_identifier, "D0004267@rdmz.com.br")
        self.assertEqual(action.expected_system_host, "nwcweb.randonconsorcios.com.br")


class DesktopActionRunTests(unittest.TestCase):
    def test_safe_file_name_removes_accents_and_preserves_extension(self) -> None:
        self.assertEqual(
            safe_file_name("número de parcelas pagas?.png"),
            "numero_de_parcelas_pagas.png",
        )
        self.assertEqual(safe_file_name("  ação: grupo/ cota * teste  "), "acao_grupo_cota_teste")
        self.assertLessEqual(len(safe_file_name("á" * 200 + ".pdf", max_length=40)), 40)

    def _run_with_final_url(self, final_url: str):
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Pagina", "url": final_url},
            "browser_mode": "desktop_browser",
            "runner": "desktop_browser_replay",
            "whether_desktop_browser_used": True,
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ):
            return asyncio.run(run_action_sync(desktop_action(), ActionRunRequest()))

    def test_desktop_browser_action_uses_desktop_replay_not_desktop_browser_replay(self) -> None:
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Pagina", "url": TARGET_URL},
            "browser_mode": "desktop_browser",
            "runner": "desktop_browser_replay",
            "whether_desktop_browser_used": True,
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(),
        ) as desktop_browser_replay, patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ) as desktop_replay:
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest(variables={"grupo": "935"})))
        desktop_replay.assert_awaited_once()
        desktop_browser_replay.assert_not_awaited()
        self.assertEqual(run.status, "success")
        self.assertTrue(run.result_payload["whether_desktop_browser_used"])  # type: ignore[index]

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
            update={"browser_mode": "desktop_browser", "url_inicial": None, "has_url": False}
        )
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Demo", "url": TARGET_URL},
        }
        with patch("backend.api.runs.find_action", return_value=action), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ):
            with authenticated_client() as client:
                response = client.post("/api/actions/teste2/run", json={"variables": {}})
                self.assertEqual(response.status_code, 200)
                created = response.json()["run"]
                listed = client.get("/api/runs").json()["runs"]
        self.assertTrue(any(item["id"] == created["id"] for item in listed))

    def test_validate_review_endpoint_creates_validation_run_and_saves_overlay(self) -> None:
        raw_action = {
            "nome_amigavel": "Teste2",
            "browser_mode": "desktop_browser",
            "url_inicial": TARGET_URL,
            "expected_system_host": "nwcweb.randonconsorcios.com.br",
            "passos_playwright": [{"tipo": "clicar", "seletor": "#buscar", "valor": ""}],
            "robust_steps": [{"tipo": "clicar", "seletor": "#buscar", "valor": ""}],
            "learning_events": [{"step_index": 0, "event_type": "click", "selector": "#buscar"}],
            "variable_schema": [],
            "variaveis_necessarias": [],
            "extraction_targets": ["Qtd. Pcls. Pagas"],
            "extraction_target": "Qtd. Pcls. Pagas",
            "objective": "número de parcelas pagas",
            "expected_result": "Retornar número de parcelas pagas",
            "ai_result_summary_enabled": False,
        }
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Consulta", "url": TARGET_URL},
            "final_page_text": "Cliente: Maria\nQtd. Pcls. Pagas: 032\nSaldo: 100",
            "final_page_dom": "<table><tr><td>Qtd. Pcls. Pagas</td><td>032</td></tr></table>",
            "dados_extraidos": {},
            "step_trace": [{"step_index": 0, "step_type": "clicar", "status": "success"}],
            "browser_mode": "desktop_browser",
            "runner": "desktop_browser_replay",
            "whether_desktop_browser_used": True,
        }
        save_learned_action("Teste2", raw_action)
        with patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ) as desktop_replay, patch(
            "backend.services.action_validation_review._ai_review",
            new=AsyncMock(
                return_value={
                    "review_status": "approved",
                    "extraction_target_confirmed": True,
                    "best_label": "Qtd. Pcls. Pagas",
                    "best_selector": "",
                    "best_value_example": "032",
                    "return_format": "somente o número",
                    "summary_instruction": (
                        "Retorne somente a quantidade de parcelas pagas encontrada no campo "
                        "Qtd. Pcls. Pagas. Não inclua outros dados da tela."
                    ),
                    "wait_suggestions": [{"after_step_index": 0, "strategy": "wait_for_text", "target": "Qtd. Pcls. Pagas"}],
                    "selector_alternatives": [],
                    "risks": [],
                    "reasoning_summary": "Alvo confirmado na tela final.",
                }
            ),
        ):
            with authenticated_client() as client:
                response = client.post("/api/actions/teste2/validate-review", json={"variables": {}, "mode": "sync"})
            self.assertEqual(response.status_code, 200)
            created = response.json()["run"]
            saved = saved_action_definition("Teste2")

        desktop_replay.assert_awaited_once()
        self.assertEqual(created["run_type"], "validation_review")
        self.assertEqual(created["status"], "success")
        self.assertEqual(saved["review_status"], "approved")
        self.assertEqual(saved["reviewed_overlay"]["extraction"]["expected_example"], "032")
        self.assertIn("Qtd. Pcls. Pagas", saved["final_summary_instruction"])
        self.assertEqual(saved["robust_steps"], raw_action["robust_steps"])
        self.assertEqual(saved["learning_events"], raw_action["learning_events"])

    def test_validate_review_accepts_accented_action_name_and_preserves_variables(self) -> None:
        raw_action = {
            "nome_amigavel": "número de parcelas pagas",
            "browser_mode": "desktop_browser",
            "url_inicial": TARGET_URL,
            "expected_system_host": "nwcweb.randonconsorcios.com.br",
            "passos_playwright": [{"tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"}],
            "robust_steps": [{"tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"}],
            "learning_events": [{"step_index": 0, "event_type": "fill", "selector": "#grupo", "variable_key": "grupo"}],
            "variable_schema": [{"key": "grupo", "label": "Grupo", "required": True}],
            "variaveis_necessarias": [{"key": "grupo", "label": "Grupo", "required": True}],
            "extraction_target": "Qtd. Pcls. Pagas",
            "objective": "número de parcelas pagas",
            "ai_result_summary_enabled": False,
        }
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Consulta", "url": TARGET_URL},
            "final_page_text": "Qtd. Pcls. Pagas: 038",
            "final_page_dom": "<td>Qtd. Pcls. Pagas</td><td>038</td>",
            "dados_extraidos": {"Qtd. Pcls. Pagas": "038"},
            "input_variables": {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
            "variables_used": {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
            "step_trace": [{"step_index": 0, "step_type": "preencher", "status": "success"}],
            "browser_mode": "desktop_browser",
            "runner": "desktop_browser_replay",
            "whether_desktop_browser_used": True,
            "screenshot_path": "data/runs/review.png",
        }
        save_learned_action("NumeroParcelas", raw_action)
        with patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ), patch("backend.services.action_validation_review._ai_review", new=AsyncMock(return_value=None)):
            with authenticated_client() as client:
                response = client.post(
                    "/api/actions/numero-de-parcelas-pagas/validate-review",
                    json={
                        "variables": {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                        "mode": "sync",
                    },
                )
            self.assertEqual(response.status_code, 200)
            created = response.json()["run"]
            saved = saved_action_definition("NumeroParcelas")

        self.assertEqual(created["status"], "success")
        self.assertEqual(created["run_type"], "validation_review")
        self.assertTrue(created["result_payload"]["validation_review"])
        self.assertEqual(created["result_payload"]["variables_used"]["grupo_3"], "00")
        self.assertEqual(created["result_payload"]["dados_extraidos"]["Qtd. Pcls. Pagas"], "038")
        self.assertEqual(saved["reviewed_overlay"]["extraction"]["expected_example"], "038")
        self.assertIn("summary_instruction", saved["reviewed_overlay"])

    def test_validation_replay_screenshot_failure_keeps_original_diagnostics(self) -> None:
        from backend.motor_browser import executar_acao_rapida

        FakeReplayContext.pages = []
        FakeReplayBrowser.contexts = []
        with patch("backend.motor_browser.async_playwright", return_value=FakeAsyncPlaywright()), patch(
            "backend.motor_browser.browser_provider", return_value=FakeReplayProvider()
        ):
            result = asyncio.run(
                executar_acao_rapida(
                    "número de parcelas pagas",
                    [{"tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"}],
                    {"grupo": "935"},
                    action_config={
                        "browser_mode": "desktop_browser",
                        "url_inicial": TARGET_URL,
                        "expected_system_host": "nwcweb.randonconsorcios.com.br",
                    },
                    run_id="run-acento",
                )
            )

        self.assertEqual(result["status"], "erro")
        diagnostics = result["page_diagnostics"]
        self.assertNotIn("_safe_file_name", result["motivo"])
        self.assertEqual(diagnostics["exception_message"], "Campo indisponivel")
        self.assertEqual(diagnostics["step_trace"][0]["status"], "error")
        self.assertEqual(diagnostics["step_trace"][0]["screenshot_path"], "")

    def test_validate_review_failure_marks_failed_and_preserves_diagnostics(self) -> None:
        raw_action = {
            "nome_amigavel": "Teste2",
            "browser_mode": "desktop_browser",
            "url_inicial": TARGET_URL,
            "expected_system_host": "nwcweb.randonconsorcios.com.br",
            "passos_playwright": [{"tipo": "clicar", "seletor": "#buscar", "valor": ""}],
            "robust_steps": [{"tipo": "clicar", "seletor": "#buscar", "valor": ""}],
            "learning_events": [{"step_index": 0, "event_type": "click", "selector": "#buscar"}],
            "variaveis_necessarias": [],
            "ai_result_summary_enabled": False,
        }
        execution = {
            "status": "erro",
            "motivo": "Falha na execução",
            "page_diagnostics": {
                "reason": "Elemento nao encontrado",
                "step_trace": [{"step_index": 0, "status": "error"}],
                "browser_mode": "desktop_browser",
                "runner": "desktop_browser_replay",
                "whether_desktop_browser_used": True,
            },
        }
        save_learned_action("Teste2", raw_action)
        with patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ):
            with authenticated_client() as client:
                response = client.post("/api/actions/teste2/validate-review", json={"variables": {}, "mode": "sync"})
            self.assertEqual(response.status_code, 200)
            saved = saved_action_definition("Teste2")

        self.assertEqual(saved["review_status"], "failed")
        self.assertEqual(saved["reviewed_overlay"]["review_status"], "failed")
        self.assertIn("diagnostics", saved["reviewed_overlay"])
        self.assertEqual(saved["robust_steps"], raw_action["robust_steps"])

    def test_async_run_persists_running_then_latest_result(self) -> None:
        action = desktop_action().model_copy(
            update={"browser_mode": "desktop_browser", "url_inicial": None, "has_url": False}
        )
        execution = {
            "status": "success",
            "texto": "concluida",
            "passos_executados": 1,
            "final_page": {"title": "Demo", "url": TARGET_URL},
        }
        with patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=execution),
        ):
            request = ActionRunRequest(mode="async", variables={"grupo": "123"})
            run = start_action_run(action, request)
            persisted = get_run(run.id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.status, "running")  # type: ignore[union-attr]

            finished = asyncio.run(finish_action_run(action, request, run))
            persisted_finished = get_run(run.id)
            with authenticated_client() as client:
                latest = client.get("/api/runs?limit=1").json()["runs"][0]

        self.assertEqual(finished.status, "success")
        self.assertIsNotNone(persisted_finished)
        self.assertEqual(persisted_finished.status, "success")  # type: ignore[union-attr]
        self.assertEqual(latest["id"], run.id)
        self.assertEqual(latest["status"], "success")
        self.assertIn("operational_summary", latest)
        self.assertEqual(latest["result_payload"]["passos_executados"], 1)

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
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(side_effect=error),
        ):
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest(variables={"grupo": "123"})))
        self.assertEqual(run.status, "error")
        self.assertEqual(run.result_payload["step_diagnostics"][0]["result"], "timeout")  # type: ignore[index]
        self.assertTrue(run.result_payload["retryable"])  # type: ignore[index]
        self.assertIn("demorou para abrir a próxima tela", run.operational_summary or "")

    def test_step_failure_keeps_required_diagnostic_payload(self) -> None:
        diagnostic = {
            "step_index": 3,
            "step_type": "preencher",
            "step_selector": "#ctl00_Conteudo_edtGrupo",
            "step_value_template": "",
            "step_variable_key": "grupo",
            "current_url": TARGET_URL,
            "current_host": "nwcweb.randonconsorcios.com.br",
            "page_title": "Consulta",
            "screenshot_path": "data/runs/run_step_3_error.png",
            "reason": "Seletor nao ficou visivel",
            "browser_mode": "desktop_browser",
            "runner": "desktop_browser_replay",
            "whether_desktop_browser_used": True,
            "last_successful_step_index": 2,
            "next_step_expected_selector": "#resultado",
            "next_step_expected_text": "Resultado",
            "step_trace": [
                {"step_index": 2, "status": "success"},
                {
                    "step_index": 3,
                    "step_type": "preencher",
                    "selector": "#ctl00_Conteudo_edtGrupo",
                    "status": "error",
                    "current_url": TARGET_URL,
                    "current_host": "nwcweb.randonconsorcios.com.br",
                    "screenshot_path": "data/runs/run_step_3_error.png",
                },
            ],
            "retryable": True,
        }
        error = RuntimeError("Erro real do Playwright")
        error.diagnostics = diagnostic  # type: ignore[attr-defined]
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(side_effect=error),
        ):
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest(variables={"grupo": "935"})))

        payload = run.result_payload or {}
        for key in (
            "run_id",
            "action_id",
            "action_key",
            "step_index",
            "step_type",
            "step_selector",
            "step_value_template",
            "step_variable_key",
            "current_url",
            "current_host",
            "page_title",
            "screenshot_path",
            "reason",
            "exception_type",
            "exception_message",
            "browser_mode",
            "runner",
            "whether_desktop_browser_used",
            "last_successful_step_index",
            "next_step_expected_selector",
            "next_step_expected_text",
            "input_variables",
            "diagnostics",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["current_url"], TARGET_URL)
        self.assertEqual(payload["current_host"], "nwcweb.randonconsorcios.com.br")
        self.assertEqual(payload["exception_message"], "Erro real do Playwright")
        self.assertEqual(payload["input_variables"]["grupo"], "935")
        self.assertEqual(payload["screenshot_path"], "data/runs/run_step_3_error.png")
        self.assertTrue(payload["whether_desktop_browser_used"])
        self.assertIn("Parei no passo 3", run.operational_summary or "")

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
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(side_effect=error),
        ):
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest()))
        self.assertEqual(run.status, "error")
        self.assertEqual(run.result_payload["session_state"], "microsoft_mfa_required")  # type: ignore[index]
        self.assertTrue(run.result_payload["operator_action_required"])  # type: ignore[index]
        self.assertEqual(run.result_payload["checkpoint_diagnostics"][0]["result"], "failed")  # type: ignore[index]
        self.assertIn("Microsoft solicitou senha ou MFA", run.operational_summary or "")

    def test_session_block_payload_keeps_next_step_diagnostic(self) -> None:
        diagnostic = {
            "session_state": "microsoft_consent_required",
            "operator_action_required": True,
            "current_host": "login.microsoftonline.com",
            "current_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "next_step_index": 1,
            "next_step_type": "preencher",
            "next_step_selector": "#ctl00_Conteudo_edtGrupo",
            "next_step_url_before": "https://nwcweb.randonconsorcios.com.br/frmMain.aspx",
            "next_step_host_before": "nwcweb.randonconsorcios.com.br",
            "reason": "next_step_is_not_click",
            "retryable": True,
        }
        error = RuntimeError("Esta tela exige intervenção manual ou não corresponde ao passo ensinado.")
        error.diagnostics = diagnostic  # type: ignore[attr-defined]
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(side_effect=error),
        ):
            run = asyncio.run(run_action_sync(desktop_action(), ActionRunRequest()))
        self.assertEqual(run.status, "error")
        self.assertEqual(run.result_payload["next_step_index"], 1)  # type: ignore[index]
        self.assertEqual(run.result_payload["next_step_type"], "preencher")  # type: ignore[index]
        self.assertEqual(run.result_payload["next_step_selector"], "#ctl00_Conteudo_edtGrupo")  # type: ignore[index]
        self.assertEqual(run.result_payload["next_step_host_before"], "nwcweb.randonconsorcios.com.br")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
