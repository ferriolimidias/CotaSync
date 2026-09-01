from __future__ import annotations

import tests  # noqa: F401

import asyncio
import json
import os
import tempfile
import unittest
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import delete

from backend.schemas.actions import ActionDetail
from backend.db import Action, ActionStep, ActionVersion, ExtractionContract, SessionLocal
from backend.schemas.runs import ActionRunRequest
from backend.services.action_runner import run_action_sync
from backend.services.actions_repository import load_actions_catalog
from backend.services.actions_repository import slugify_action_id
from backend.services.demo_session import DemoSessionManager, _normalize_variable_key
from backend.services.external_systems import load_current_external_system, save_current_external_system
from backend.services.operational_summary import build_operational_summary
from backend.services.runtime_files import runtime_download_path, runtime_file_metadata


def _review() -> dict[str, object]:
    return {
        "ai_reviewed": False,
        "ai_observer_summary": "Síntese local concluída.",
        "replay_hints": ["Aguardar o resultado."],
        "waits": [],
        "variable_schema": [{"key": "codigo", "label": "Código", "required": True}],
        "extraction_target": "status",
        "suggested_extraction_targets": [],
        "suggested_objective": "Consultar status",
        "suggested_expected_result": "Retornar status",
        "ai_slow_system_notes": [],
        "ai_risk_notes": [],
    }


class FakePage:
    url = "https://example.test/consulta"

    def is_closed(self) -> bool:
        return False

    async def title(self) -> str:
        return "Consulta"

    async def screenshot(self, **_kwargs: object) -> None:
        return None


class FakeBrowser:
    def is_connected(self) -> bool:
        return True


class CanonicalClientFieldTests(unittest.TestCase):
    def test_version_label_and_legacy_alias_use_canonical_key(self) -> None:
        self.assertEqual(_normalize_variable_key("Versão"), "versao")
        self.assertEqual(_normalize_variable_key("vers_o"), "versao")


class FakeLocator:
    async def fill(self, _value: str, **_kwargs: object) -> None:
        return None

    async def select_option(self, _value: str, **_kwargs: object) -> None:
        return None

    async def click(self, **_kwargs: object) -> None:
        return None

    async def evaluate(self, *_args: object, **_kwargs: object) -> None:
        return None


class FakeSelectLocator(FakeLocator):
    async def evaluate(self, *args: object, **_kwargs: object) -> object:
        script = str(args[0] if args else "")
        if "tag:" in script and "placeholder" in script:
            return {"tag": "select", "id": "", "name": "", "label": "", "placeholder": "", "aria_label": ""}
        return None


def _session(*, download_detected: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id="session",
        steps=[
            {"tipo": "preencher", "seletor": "#codigo", "valor": ""},
            {"tipo": "clicar", "seletor": "#buscar", "valor": ""},
        ],
        learning_events=[
            {"step_index": 0, "event_type": "fill", "selector": "#codigo"},
            {
                "step_index": 1,
                "event_type": "click",
                "selector": "#buscar",
                "download_detected": download_detected,
            },
        ],
        guided_learning={
            "name": "Consultar status",
            "objective": "Consultar o status real",
            "input_description": "Código informado pelo usuário",
            "expected_result": "Retornar o status",
            "success_criteria": "Status visível",
            "output_type": "texto/dados da tela",
        },
        learning_synthesis={},
        final_page_snapshot={},
        download_detected=download_detected,
        recording=True,
        status="gravando",
        operator_recording_suppressed_until=0.0,
        operator_fill_attempt_count=0,
        operator_fill_recorded_count=0,
        operator_click_attempt_count=0,
        operator_click_recorded_count=0,
        active_recording_session_id="session",
        last_operator_result={},
        last_backend_recorded_event={},
        last_recorded_event_session_id="",
        result_selection={},
        extraction_review={},
        observer_tasks=set(),
        context=SimpleNamespace(pages=[]),
        storage_state_path=Path(tempfile.gettempdir()) / "cotasync-unit" / "storage_state.json",
        last_screenshot_path="",
        last_page_count=0,
        recorder_errors=[],
        browser_mode="desktop_browser",
        browser=FakeBrowser(),
        external_system_name="",
        external_login_url="",
        access_profile_name="",
        access_profile_email_or_identifier="",
        microsoft_saved_account_identifier="",
        microsoft_saved_account_selector="",
        microsoft_saved_account_text="",
        expected_system_host="",
        microsoft_hosts=[],
        page=FakePage(),
    )


def _external_session() -> SimpleNamespace:
    session = _session()
    session.browser_mode = "desktop_browser"
    session.external_system_name = "Sistema Priscila e Jonatan"
    session.external_login_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    session.access_profile_name = "Priscila"
    session.access_profile_email_or_identifier = "D0004267@rdmz.com.br"
    session.microsoft_saved_account_identifier = "D0004267@rdmz.com.br"
    session.microsoft_saved_account_selector = ""
    session.microsoft_saved_account_text = "Priscila Susin"
    session.expected_system_host = "nwcweb.randonconsorcios.com.br"
    session.microsoft_hosts = ["login.microsoftonline.com", "m365.cloud.microsoft"]
    return session


class GuidedLearningSaveTests(unittest.TestCase):
    FULL_MICROSOFT_URL = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
        "client_id=abc&response_type=code&response_mode=query&scope=openid&"
        "redirect_uri=https%3A%2F%2Fnwcweb.randonconsorcios.com.br%2FfrmCorCCCnsLogin.aspx&"
        "state=XYZ&prompt=consent"
    )

    def test_external_system_url_round_trip_preserves_complete_string(self) -> None:
        saved = save_current_external_system(
            {
                "external_system_name": "Sistema externo",
                "external_login_url": self.FULL_MICROSOFT_URL,
                "expected_system_host": "nwcweb.randonconsorcios.com.br",
            }
        )
        loaded = load_current_external_system()

        self.assertEqual(saved["external_login_url"], self.FULL_MICROSOFT_URL)
        self.assertEqual(loaded["external_login_url"], self.FULL_MICROSOFT_URL)
        self.assertEqual(saved["expected_system_host"], "nwcweb.randonconsorcios.com.br")

    def test_saved_session_target_uses_complete_external_url_not_expected_host(self) -> None:
        manager = DemoSessionManager()
        session = _external_session()
        session.external_login_url = self.FULL_MICROSOFT_URL
        session.expected_system_host = "nwcweb.randonconsorcios.com.br"

        self.assertEqual(manager._target_url_for_saved_session(session), self.FULL_MICROSOFT_URL)
        self.assertNotEqual(manager._target_url_for_saved_session(session), "https://nwcweb.randonconsorcios.com.br")

    def test_action_initial_url_preserves_configured_url_when_learning_starts_there(self) -> None:
        manager = DemoSessionManager()
        session = _external_session()
        session.external_login_url = self.FULL_MICROSOFT_URL
        session.steps = [{"tipo": "clicar", "seletor": "#accept", "valor": ""}]
        session.learning_events = [
            {
                "step_index": 0,
                "event_type": "click",
                "selector": "#accept",
                "url_before": self.FULL_MICROSOFT_URL,
                "url_after": "https://nwcweb.randonconsorcios.com.br/frmMain.aspx?x=1",
            }
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Login completo", "Consulta.", {}))

        action = captured["acoes_conhecidas"]["Login completo"]  # type: ignore[index]
        self.assertEqual(action["url_inicial"], self.FULL_MICROSOFT_URL)
        self.assertNotEqual(action["url_inicial"], "https://m365.cloud.microsoft/search")

    def test_action_initial_url_uses_current_learning_url_when_recording_from_current_screen(self) -> None:
        manager = DemoSessionManager()
        session = _external_session()
        session.external_login_url = self.FULL_MICROSOFT_URL
        current_url = "https://nwcweb.randonconsorcios.com.br/frmMain.aspx?filtro=abc&state=keep"
        session.steps = [{"tipo": "preencher", "seletor": "#grupo", "valor": "", "variavel": "grupo"}]
        session.learning_events = [
            {
                "step_index": 0,
                "event_type": "fill",
                "selector": "#grupo",
                "url_before": current_url,
                "url_after": current_url,
            }
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Tela atual", "Consulta.", {"0": "grupo"}))

        action = captured["acoes_conhecidas"]["Tela atual"]  # type: ignore[index]
        self.assertEqual(action["url_inicial"], current_url)

    def test_empty_external_system_has_no_real_access_profile_defaults(self) -> None:
        config = load_current_external_system()
        self.assertEqual(config["access_profile_name"], "")
        self.assertEqual(config["microsoft_saved_account_text"], "")
        self.assertEqual(config["microsoft_saved_account_identifier"], "")
        self.assertEqual(config["expected_system_host"], "")
        self.assertIn("m365.cloud.microsoft", config["microsoft_hosts"])

    def test_learning_can_start_with_only_action_name(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.status = "autenticada"
        session.recording = False
        session.observer_tasks = set()
        session.context = SimpleNamespace(pages=[])
        session.storage_state_path = Path(tempfile.gettempdir()) / "cotasync-unit" / "storage_state.json"
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_install_recorder_for_session", new=AsyncMock()), patch.object(
            manager,
            "status",
            new=AsyncMock(return_value={"id": "session", "recording": True}),
        ):
            result = asyncio.run(manager.start_recording("session", {"name": "Consultar parcelas"}))
        self.assertTrue(session.recording)
        self.assertEqual(session.guided_learning["name"], "Consultar parcelas")
        self.assertEqual(session.guided_learning["objective"], "")
        self.assertTrue(session.guided_learning["ai_result_summary_enabled"])
        self.assertEqual(result["id"], "session")

    def test_recording_can_start_from_waiting_login_screen(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.status = "aguardando_login"
        session.recording = False
        session.observer_tasks = set()
        session.context = SimpleNamespace(pages=[])
        session.storage_state_path = Path(tempfile.gettempdir()) / "cotasync-unit" / "waiting-login-state.json"
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_install_recorder_for_session", new=AsyncMock()), patch.object(
            manager,
            "status",
            new=AsyncMock(return_value={"id": "session", "status": "gravando", "recording": True}),
        ):
            result = asyncio.run(manager.start_recording("session", {"name": "Gravar login"}))
        self.assertTrue(session.recording)
        self.assertEqual(session.status, "gravando")
        self.assertEqual(result["status"], "gravando")

    def test_status_exposes_saved_session_metadata(self) -> None:
        manager = DemoSessionManager()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "storage_state.json"
            state_path.write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
            session = _session()  # type: ignore[assignment]
            session.status = "aguardando_login"
            session.storage_state_path = state_path
            session.created_at = "2026-01-01T00:00:00+00:00"
            session.tracking_id = "cotasync-session"
            session.live_url = ""
            session.public_devtools_host = ""
            session.page = SimpleNamespace(
                url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                title=AsyncMock(return_value="Sign in to your account"),
                is_closed=lambda: False,
            )
            session.browser = FakeBrowser()
            session.target_id = "target"
            session.external_system_name = "Sistema"
            session.external_login_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            session.expected_system_host = "nwcweb.randonconsorcios.com.br"
            session.microsoft_hosts = ["login.microsoftonline.com"]
            session.auth_validation_mode = "manual_confirmation"
            session.profile_reference = "/data/profile"
            session.manual_login_confirmed = False
            session.confirmed_page_url = ""
            session.confirmed_page_title = ""
            manager._sessions["session"] = session  # type: ignore[attr-defined]

            result = asyncio.run(manager.status("session"))

        self.assertTrue(result["saved_session_exists"])
        self.assertTrue(result["storage_state_saved"])
        self.assertIsNotNone(result["saved_session_last_saved_at"])
        self.assertEqual(result["saved_session_test_status"], "microsoft_login")
        self.assertEqual(result["saved_session_current_title"], "Sign in to your account")

    def test_guided_metadata_and_extraction_are_saved_and_sent_to_synthesis(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}

        def save(payload: dict[str, object]) -> None:
            captured.update(payload)

        analyzer = AsyncMock(return_value=_review())
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: save({"acoes_conhecidas": {action_key: learned_action}})), patch("backend.services.ai_observer.analyze_recorded_action_with_ai", analyzer):
            saved = asyncio.run(
                manager.save_action(
                    "session",
                    "Consultar status",
                    "Consulta guiada.",
                    {"0": "codigo"},
                    objective="Consultar o status real",
                    input_description="Código informado pelo usuário",
                    expected_result="Retornar o status",
                    success_criteria="Status visível",
                    output_type="texto/dados da tela",
                    extraction_targets=[{"label": "status", "selector": "#status"}],
                    ai_result_summary_enabled=False,
                    ai_recovery_enabled=False,
                )
            )

        action = captured["acoes_conhecidas"]["Consultar status"]  # type: ignore[index]
        self.assertEqual(action["objective"], "Consultar o status real")
        self.assertEqual(action["input_description"], "Código informado pelo usuário")
        self.assertEqual(action["expected_result"], "Retornar o status")
        self.assertEqual(action["success_criteria"], "Status visível")
        self.assertEqual(action["output_type"], "texto/dados da tela")
        self.assertFalse(action["ai_result_summary_enabled"])
        self.assertFalse(action["ai_recovery_enabled"])
        self.assertEqual(action["extraction_targets"], ["status"])
        self.assertEqual(action["passos_playwright"][-1]["tipo"], "extrair_texto")
        synthesis_action = analyzer.await_args.args[0]
        self.assertEqual(synthesis_action["objective"], "Consultar o status real")
        self.assertEqual(synthesis_action["expected_result"], "Retornar o status")
        self.assertEqual(saved["extraction_targets"], ["status"])

    def test_ai_summary_defaults_on_when_saving(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Consultar default IA", "Consulta.", {}))
        action = captured["acoes_conhecidas"]["Consultar default IA"]  # type: ignore[index]
        self.assertTrue(action["ai_result_summary_enabled"])

    def test_download_detected_action_converts_click_to_file_output(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session(download_detected=True)  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(
                manager.save_action(
                    "session",
                    "Baixar relatório",
                    "Gera arquivo.",
                    {"0": "codigo"},
                    output_type="arquivo/PDF",
                    return_downloaded_file=True,
                )
            )
        action = captured["acoes_conhecidas"]["Baixar relatório"]  # type: ignore[index]
        self.assertEqual(action["passos_playwright"][1]["tipo"], "download_pdf")
        self.assertEqual(action["output_schema"]["main_file"]["type"], "file")
        self.assertTrue(action["download_expected"])

    def test_typed_extraction_target_is_saved_as_near_label_strategy(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(
                manager.save_action(
                    "session",
                    "Consultar parcelas pagas",
                    "Consulta.",
                    {},
                    extraction_targets=[{"label": "Qtd. Pcls. Pagas"}],
                )
            )
        action = captured["acoes_conhecidas"]["Consultar parcelas pagas"]  # type: ignore[index]
        extraction_step = action["passos_playwright"][-1]
        self.assertEqual(extraction_step["tipo"], "extrair_texto")
        self.assertEqual(extraction_step["nome"], "Qtd. Pcls. Pagas")
        self.assertEqual(extraction_step["seletor"], "")
        self.assertEqual(extraction_step["extraction_strategy"], "near_label")

    def test_confirmed_visual_result_is_saved_with_learned_action(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.extraction_review = {
            "source": "visual_result_selection",
            "target_name": "Qtd. Pcls. Pagas",
            "screen_label": "Qtd. Pcls. Pagas",
            "selection_type": "field_value",
            "example_value": "040",
            "expected_example": "040",
            "normalization": {"type": "digits_only"},
            "selector_data": {"primary": "#parcelas"},
            "anchor_data": {"context_label": "Qtd. Pcls. Pagas"},
            "summary_instruction": "Retorne somente o valor do resultado selecionado.",
        }
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Consultar parcelas pagas", "Consulta.", {}))
        action = captured["acoes_conhecidas"]["Consultar parcelas pagas"]  # type: ignore[index]

        self.assertEqual(action["extraction_review"]["expected_example"], "040")
        self.assertEqual(action["extraction_review"]["normalization"]["type"], "digits_only")
        self.assertEqual(action["reviewed_overlay"]["extraction"]["screen_label"], "Qtd. Pcls. Pagas")
        self.assertIn("Qtd. Pcls. Pagas", action["extraction_targets"])

    def test_visual_result_publish_persists_steps_and_contract_in_postgres(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [
            {"tipo": "preencher", "seletor": "#grupo", "valor": ""},
            {"tipo": "preencher", "seletor": "#cota", "valor": ""},
            {"tipo": "selecionar", "seletor": "#versao", "valor": ""},
            *({"tipo": "clicar", "seletor": f"#passo-{index}", "valor": ""} for index in range(4, 9)),
        ]
        session.learning_events = [
            {"step_index": index, "event_type": "fill" if index < 2 else "click", "selector": step["seletor"]}
            for index, step in enumerate(session.steps)
        ]
        session.recording = False
        session.status = "finalizado"
        session.result_selection = {
            "status": "captured",
            "candidates": [
                {
                    "label": "Número de parcelas",
                    "value": "040",
                    "type": "field_value",
                    "selected_element": {
                        "selector": "#numero-parcelas",
                        "tag_name": "span",
                        "nearby_text_before": ["Número de parcelas"],
                    },
                }
            ],
        }
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        asyncio.run(
            manager.confirm_result_selection(
                "session",
                target_name="Número de parcelas",
                screen_label="Número de parcelas",
                normalization="digits_only",
            )
        )

        action_name = f"Teste publicação visual {uuid4().hex[:8]}"
        action_id = slugify_action_id(action_name)
        try:
            with patch(
                "backend.services.ai_observer.analyze_recorded_action_with_ai",
                new=AsyncMock(return_value=_review()),
            ), patch("backend.services.actions_repository.find_action", return_value=None):
                asyncio.run(
                    manager.save_action(
                        "session",
                        action_name,
                        "Consulta.",
                        {"0": "grupo", "1": "cota", "2": "versao"},
                        objective="Consultar quantidade de parcelas",
                        expected_result="Número de parcelas",
                    )
                )

            with SessionLocal() as db:
                action = db.get(Action, action_id)
                self.assertIsNotNone(action)
                version = db.get(ActionVersion, action.published_version_id)
                self.assertIsNotNone(version)
                steps = db.query(ActionStep).filter(ActionStep.action_version_id == version.id).all()
                contract = db.query(ExtractionContract).filter(ExtractionContract.action_version_id == version.id).one()
                self.assertEqual(len(steps), 8)
                self.assertEqual(contract.example_value, "040")
                self.assertEqual(contract.selector_data["primary"], "#numero-parcelas")
                self.assertNotEqual(contract.selector_data["primary"], contract.example_value)
        finally:
            with SessionLocal.begin() as db:
                version = db.query(ActionVersion).filter(ActionVersion.action_id == action_id).one_or_none()
                if version is not None:
                    db.execute(delete(ExtractionContract).where(ExtractionContract.action_version_id == version.id))
                    db.execute(delete(ActionStep).where(ActionStep.action_version_id == version.id))
                    db.execute(delete(ActionVersion).where(ActionVersion.id == version.id))
                existing_action = db.get(Action, action_id)
                if existing_action is not None:
                    db.execute(delete(Action).where(Action.id == action_id))

    def test_publish_without_visual_extraction_keeps_contract_optional(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch(
            "backend.services.demo_session.save_learned_action",
            side_effect=lambda action_key, learned_action: captured.update(
                {"acoes_conhecidas": {action_key: learned_action}}
            ),
        ), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Ação sem extração", "Consulta.", {}))

        action = captured["acoes_conhecidas"]["Ação sem extração"]  # type: ignore[index]
        self.assertEqual(action["extraction_review"], {})
        self.assertFalse(any(step.get("tipo") == "extrair_texto" for step in action["passos_playwright"]))

    def test_confirming_result_twice_replaces_session_contract(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.result_selection = {
            "status": "captured",
            "candidates": [{"label": "Qtd. Pcls. Pagas", "value": "040", "type": "field_value"}],
        }
        manager._sessions["session"] = session  # type: ignore[attr-defined]

        first = asyncio.run(
            manager.confirm_result_selection(
                "session",
                target_name="Qtd. Pcls. Pagas",
                screen_label="Qtd. Pcls. Pagas",
                normalization="digits_only",
            )
        )
        session.result_selection = {
            "status": "captured",
            "candidates": [{"label": "Qtd. Pcls. Pagas", "value": "041", "type": "field_value"}],
        }
        second = asyncio.run(
            manager.confirm_result_selection(
                "session",
                target_name="Qtd. Pcls. Pagas",
                screen_label="Qtd. Pcls. Pagas",
                normalization="digits_only",
            )
        )

        self.assertEqual(first["extraction_review"]["expected_example"], "040")
        self.assertEqual(second["extraction_review"]["expected_example"], "041")
        self.assertEqual(session.extraction_review["expected_example"], "041")

    def test_variable_names_are_suggested_as_friendly_schema_and_renamable(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [
            {"tipo": "preencher", "seletor": "#ctl00_Conteudo_edtGrupo", "valor": ""},
            {"tipo": "preencher", "seletor": "#ctl00_Conteudo_edtCota", "valor": ""},
            {"tipo": "selecionar", "seletor": "select:nth-of-type(1)", "valor": ""},
        ]
        session.learning_events = [
            {"step_index": 0, "event_type": "fill", "selector": "#ctl00_Conteudo_edtGrupo"},
            {"step_index": 1, "event_type": "fill", "selector": "#ctl00_Conteudo_edtCota"},
            {"step_index": 2, "event_type": "select", "selector": "select:nth-of-type(1)"},
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            saved = asyncio.run(
                manager.save_action(
                    "session",
                    "Consultar parcela",
                    "Consulta.",
                    {"0": "conteudo_edtgrupo", "1": "conteudo_edtcota", "2": "tipo_consulta"},
                )
            )
        action = captured["acoes_conhecidas"]["Consultar parcela"]  # type: ignore[index]
        self.assertEqual([item["key"] for item in action["variaveis_necessarias"]], ["grupo", "cota", "tipo_consulta"])
        self.assertEqual([item["label"] for item in action["variable_schema"]], ["Grupo", "Cota", "Tipo Consulta"])
        self.assertEqual(action["passos_playwright"][0]["value_template"], "{{grupo}}")
        self.assertEqual(action["learning_events"][0]["variable_key"], "grupo")
        self.assertEqual(action["learning_events"][0]["value_template"], "{{grupo}}")
        self.assertEqual(action["passos_playwright"][2]["tipo"], "selecionar")
        self.assertEqual(action["passos_playwright"][2]["value_template"], "{{tipo_consulta}}")
        self.assertEqual([item["key"] for item in saved["variables"]], ["grupo", "cota", "tipo_consulta"])

    def test_fill_event_creates_variable_without_manual_mapping_and_never_fixed_value(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [
            {
                "tipo": "preencher",
                "seletor": "#ctl00_Conteudo_edtGrupo",
                "valor": "935",
                "field_metadata": {"id": "ctl00_Conteudo_edtGrupo", "label": "Grupo"},
            }
        ]
        session.learning_events = [
            {
                "step_index": 0,
                "event_type": "fill",
                "selector": "#ctl00_Conteudo_edtGrupo",
                "field_metadata": {"id": "ctl00_Conteudo_edtGrupo", "label": "Grupo"},
            }
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Consultar grupo", "Consulta.", {}))
        action = captured["acoes_conhecidas"]["Consultar grupo"]  # type: ignore[index]
        step = action["passos_playwright"][0]
        self.assertEqual(step["variavel"], "grupo")
        self.assertEqual(step["valor"], "")
        self.assertEqual(step["value_template"], "{{grupo}}")
        self.assertNotIn("935", json.dumps(action, ensure_ascii=False))

    def test_textarea_field_also_creates_generic_variable_without_fixed_value(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [
            {
                "tipo": "preencher",
                "seletor": "textarea[name=\"nome\"]",
                "valor": "Maria Silva",
                "field_metadata": {"tag": "textarea", "name": "nome", "label": "Nome"},
            }
        ]
        session.learning_events = [
            {
                "step_index": 0,
                "event_type": "fill",
                "selector": "textarea[name=\"nome\"]",
                "field_metadata": {"tag": "textarea", "name": "nome", "label": "Nome"},
            }
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Consultar nome", "Consulta.", {}))
        action = captured["acoes_conhecidas"]["Consultar nome"]  # type: ignore[index]
        step = action["passos_playwright"][0]
        self.assertEqual(step["variavel"], "nome")
        self.assertEqual(step["valor"], "")
        self.assertEqual(step["value_template"], "{{nome}}")
        self.assertNotIn("Maria Silva", json.dumps(action, ensure_ascii=False))

    def test_iframe_and_new_page_metadata_are_preserved(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [{"tipo": "preencher", "seletor": "#edtCota", "valor": ""}]
        session.learning_events = [
            {
                "step_index": 0,
                "event_type": "fill",
                "selector": "#edtCota",
                "frame_url": "https://example.test/frame",
                "frame_name": "consulta",
                "opened_new_page": True,
            }
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Consultar iframe", "Consulta.", {}))
        action = captured["acoes_conhecidas"]["Consultar iframe"]  # type: ignore[index]
        self.assertEqual(action["robust_steps"][0]["frame_url"], "https://example.test/frame")
        self.assertEqual(action["robust_steps"][0]["frame_name"], "consulta")
        self.assertTrue(action["robust_steps"][0]["opened_new_page"])
        self.assertEqual(action["robust_steps"][0]["page_ref"], "main")
        self.assertIn("learned_states", action)
        self.assertIn("learned_transitions", action)

    def test_operator_fill_records_directly_when_listener_misses_event(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session()  # type: ignore[attr-defined]
        manager._sessions["session"].steps = []  # type: ignore[attr-defined]
        recorder = AsyncMock()
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeLocator())), patch.object(
            manager,
            "_record_live_step",
            new=recorder,
        ):
            recorder.return_value = {
                "session_id": "session",
                "event_type": "fill",
                "selector": "#ctl00_Conteudo_edtGrupo",
                "source": "operator_mode",
                "variable_key": "grupo",
            }
            result = asyncio.run(manager.operator_fill("session", "#ctl00_Conteudo_edtGrupo", "123", record_action=True))
        self.assertTrue(result["recorded"])
        raw_event = recorder.await_args.args[1]
        self.assertEqual(raw_event["tipo"], "preencher")
        self.assertEqual(raw_event["event_type"], "fill")
        self.assertEqual(raw_event["seletor"], "#ctl00_Conteudo_edtGrupo")
        self.assertEqual(raw_event["variable_key"], "grupo")
        self.assertEqual(raw_event["value_template"], "{{grupo}}")
        self.assertEqual(raw_event["source"], "operator_mode")

    def test_operator_fill_during_recording_creates_variable_step_and_diagnostics(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeLocator())):
            result = asyncio.run(manager.operator_fill("session", "#ctl00_Conteudo_edtGrupo", "123", record_action=True))
        self.assertTrue(result["recorded"])
        self.assertEqual(session.steps[0]["tipo"], "preencher")
        self.assertEqual(session.steps[0]["variavel"], "grupo")
        self.assertEqual(session.steps[0]["valor"], "")
        self.assertEqual(session.steps[0]["value_template"], "{{grupo}}")
        self.assertEqual(session.learning_events[0]["event_type"], "fill")
        self.assertEqual(session.learning_events[0]["source"], "operator_mode")
        self.assertEqual(session.learning_events[0]["variable_key"], "grupo")
        diagnostics = asyncio.run(manager.recording_diagnostics("session"))
        self.assertEqual(diagnostics["fill_event_count"], 1)
        self.assertEqual(diagnostics["operator_fill_count"], 1)
        self.assertEqual(diagnostics["operator_fill_attempt_count"], 1)

    def test_operator_fill_with_stale_ui_record_action_false_still_records_active_session(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        session.active_recording_session_id = "session"
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeLocator())):
            result = asyncio.run(
                manager.operator_fill(
                    "session",
                    "#ctl00_Conteudo_edtGrupo",
                    "123",
                    record_action=False,
                    active_recording_session_id="session",
                )
            )
        self.assertTrue(result["recorded"])
        self.assertEqual(result["operator_request_session_id"], "session")
        self.assertEqual(result["active_recording_session_id"], "session")
        self.assertEqual(result["last_recorded_event_session_id"], "session")
        self.assertEqual(result["event_type"], "fill")
        self.assertEqual(session.operator_fill_attempt_count, 1)
        self.assertEqual(session.operator_fill_recorded_count, 1)
        self.assertEqual(session.learning_events[0]["session_id"], "session")
        self.assertEqual(session.learning_events[0]["source"], "operator_mode")

    def test_operator_fill_session_id_mismatch_is_rejected(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.active_recording_session_id = "session"
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with self.assertRaisesRegex(Exception, "Sessao ativa"):
            asyncio.run(
                manager.operator_fill(
                    "session",
                    "#ctl00_Conteudo_edtGrupo",
                    "123",
                    record_action=True,
                    active_recording_session_id="other-session",
                )
            )

    def test_operator_fill_during_login_screen_records_when_recording_active(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.status = "gravando"
        session.recording = True
        session.page.url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        session.steps = []
        session.learning_events = []
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeLocator())):
            result = asyncio.run(manager.operator_fill("session", "#ctl00_Conteudo_edtGrupo", "123"))
        self.assertTrue(result["recorded"])
        self.assertEqual(session.learning_events[0]["event_type"], "fill")
        self.assertEqual(session.learning_events[0]["url_before"], "https://login.microsoftonline.com/common/oauth2/v2.0/authorize")

    def test_operator_fill_outside_recording_does_not_create_learned_variable(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        session.recording = False
        session.status = "autenticada"
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeLocator())):
            result = asyncio.run(manager.operator_fill("session", "#ctl00_Conteudo_edtGrupo", "123", record_action=False))
        self.assertFalse(result["recorded"])
        self.assertEqual(session.steps, [])
        self.assertEqual(session.learning_events, [])
        self.assertEqual(session.operator_fill_attempt_count, 0)

    def test_normal_input_textarea_and_select_events_create_variables(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        asyncio.run(
            manager.record_field_variable_event(
                "session",
                "#ctl00_Conteudo_edtGrupo",
                field_kind="input",
                source="browser_recorder",
                example_value="935",
                field_metadata={"id": "ctl00_Conteudo_edtGrupo", "label": "Grupo"},
            )
        )
        asyncio.run(
            manager.record_field_variable_event(
                "session",
                "textarea[name=\"cliente\"]",
                field_kind="textarea",
                source="browser_recorder",
                example_value="Maria",
                field_metadata={"tag": "textarea", "name": "cliente", "label": "Cliente"},
            )
        )
        asyncio.run(
            manager.record_field_variable_event(
                "session",
                "select:nth-of-type(1)",
                field_kind="select",
                source="browser_recorder",
                example_value="A",
                field_metadata={"tag": "select"},
            )
        )
        self.assertEqual([step["tipo"] for step in session.steps], ["preencher", "preencher", "selecionar"])
        self.assertEqual([step["variavel"] for step in session.steps], ["grupo", "cliente", "tipo_consulta"])
        self.assertEqual([step["valor"] for step in session.steps], ["", "", ""])
        self.assertEqual([event["event_type"] for event in session.learning_events], ["fill", "fill", "select"])
        diagnostics = asyncio.run(manager.recording_diagnostics("session"))
        self.assertEqual(diagnostics["fill_event_count"], 2)
        self.assertEqual(diagnostics["select_event_count"], 1)
        self.assertEqual(diagnostics["direct_typing_capture_status"], "field_events_observed")

    def test_variable_key_suggestions_cover_cota_and_unknown_selector(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        asyncio.run(
            manager.record_field_variable_event(
                "session",
                "#ctl00_Conteudo_edtCota",
                field_kind="input",
                source="browser_recorder",
            )
        )
        asyncio.run(
            manager.record_field_variable_event(
                "session",
                "div:nth-of-type(3) > input:nth-of-type(1)",
                field_kind="input",
                source="browser_recorder",
            )
        )
        self.assertEqual(session.steps[0]["variavel"], "cota")

        unknown_session = _session()  # type: ignore[assignment]
        unknown_session.steps = []
        unknown_session.learning_events = []
        manager._sessions["unknown"] = unknown_session  # type: ignore[attr-defined]
        asyncio.run(
            manager.record_field_variable_event(
                "unknown",
                "div:nth-of-type(3) > input:nth-of-type(1)",
                field_kind="input",
                source="browser_recorder",
            )
        )
        self.assertEqual(unknown_session.steps[0]["variavel"], "campo_1")

    def test_operator_select_records_select_variable(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeSelectLocator())):
            asyncio.run(manager.operator_fill("session", "select:nth-of-type(1)", "tipo", record_action=True))
        self.assertEqual(session.steps[0]["tipo"], "selecionar")
        self.assertEqual(session.steps[0]["variavel"], "tipo_consulta")
        self.assertEqual(session.learning_events[0]["event_type"], "select")

    def test_stop_recording_returns_latest_operator_counts_in_review(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [{"tipo": "preencher", "seletor": "#ctl00_Conteudo_edtGrupo", "valor": "", "variavel": "grupo"}]
        session.learning_events = [
            {
                "session_id": "session",
                "step_index": 0,
                "event_type": "fill",
                "selector": "#ctl00_Conteudo_edtGrupo",
                "source": "operator_mode",
                "variable_key": "grupo",
            }
        ]
        session.operator_fill_attempt_count = 1
        session.operator_fill_recorded_count = 1
        session.active_recording_session_id = "session"
        session.last_recorded_event_session_id = "session"
        session.last_backend_recorded_event = {
            "session_id": "session",
            "event_id": 0,
            "event_type": "fill",
            "selector": "#ctl00_Conteudo_edtGrupo",
            "source": "operator_mode",
            "variable_key": "grupo",
        }
        session.last_operator_result = {
            "session_id": "session",
            "operator_request_session_id": "session",
            "recorded": True,
            "event_id": 0,
            "event_type": "fill",
        }
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_evaluate_all_frames", new=AsyncMock(return_value=[])), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ), patch.object(manager, "status", new=AsyncMock(return_value={"id": "session", "status": "autenticada"})):
            result = asyncio.run(manager.stop_recording("session"))
        review = result["review_summary"]
        self.assertEqual(review["reviewed_session_id"], "session")
        self.assertEqual(review["active_recording_session_id"], "session")
        self.assertEqual(review["last_recorded_event_session_id"], "session")
        self.assertEqual(review["fills_captured"], 1)
        self.assertEqual(review["operator_fill_attempt_count"], 1)
        self.assertEqual(review["operator_fill_count"], 1)
        self.assertEqual(review["diagnostics"]["raw_event_count"], 1)

    def test_missing_expected_input_capture_is_persisted_as_warning(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [{"tipo": "clicar", "seletor": "#buscar", "valor": ""}]
        session.learning_events = [{"step_index": 0, "event_type": "click", "selector": "#buscar"}]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            saved = asyncio.run(
                manager.save_action(
                    "session",
                    "Consultar parcela sem campos",
                    "Consulta.",
                    {},
                    input_description="Grupo e cota informados pelo usuário",
                )
            )
        action = captured["acoes_conhecidas"]["Consultar parcela sem campos"]  # type: ignore[index]
        self.assertEqual(action["variable_schema"], [])
        self.assertEqual(action["variaveis_necessarias"], [])
        self.assertIn("Não identifiquei os campos digitados", action["learning_warnings"][0])
        self.assertEqual(saved["learning_warnings"], action["learning_warnings"])

    def test_actions_catalog_exposes_variables_after_learning(self) -> None:
        payload = {
            "acoes_conhecidas": {
                "Consultar parcela": {
                    "nome_amigavel": "Consultar parcela",
                    "passos_playwright": [
                        {
                            "tipo": "preencher",
                            "seletor": "#ctl00_Conteudo_edtGrupo",
                            "valor": "",
                            "variavel": "grupo",
                            "value_template": "{{grupo}}",
                        }
                    ],
                    "variaveis_necessarias": [{"key": "grupo", "label": "Grupo", "required": True}],
                    "variable_schema": [{"key": "grupo", "label": "Grupo", "required": True}],
                }
            }
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as tmp:
            json.dump(payload, tmp)
            tmp.flush()
            catalog = load_actions_catalog(Path(tmp.name))
        self.assertEqual(catalog.actions[0].variables[0].key, "grupo")
        self.assertEqual(catalog.actions[0].variables[0].label, "Grupo")

    def test_saved_operator_fill_exposes_quick_execution_variable(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = []
        session.learning_events = []
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        with patch.object(manager, "_operator_locator", new=AsyncMock(return_value=FakeLocator())):
            asyncio.run(manager.operator_fill("session", "#ctl00_Conteudo_edtGrupo", "123", record_action=True))
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            saved = asyncio.run(manager.save_action("session", "Consultar grupo", "Consulta.", {}))
        self.assertEqual(
            saved["variables"],
            [{"key": "grupo", "label": "Grupo", "required": True, "source": "client"}],
        )
        action = captured["acoes_conhecidas"]["Consultar grupo"]  # type: ignore[index]
        self.assertEqual(action["passos_playwright"][0]["variavel"], "grupo")
        self.assertEqual(action["passos_playwright"][0]["value_template"], "{{grupo}}")

    def test_external_learned_action_saves_access_profile_metadata(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _external_session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            saved = asyncio.run(
                manager.save_action(
                    "session",
                    "Consultar externo",
                    "Consulta externa.",
                    {"0": "codigo"},
                )
            )
        action = captured["acoes_conhecidas"]["Consultar externo"]  # type: ignore[index]
        self.assertEqual(action["access_profile_name"], "Priscila")
        self.assertEqual(action["microsoft_saved_account_text"], "Priscila Susin")
        self.assertEqual(action["microsoft_saved_account_identifier"], "D0004267@rdmz.com.br")
        self.assertEqual(action["expected_system_host"], "nwcweb.randonconsorcios.com.br")
        self.assertTrue(action["requires_authenticated_session"])
        self.assertTrue(action["session_guardian_enabled"])
        self.assertEqual(saved["access_profile_name"], "Priscila")

    def test_microsoft_click_metadata_is_kept_in_robust_steps(self) -> None:
        manager = DemoSessionManager()
        session = _external_session()
        session.steps = [
            {
                "tipo": "clicar",
                "seletor": 'div[aria-label="Sign in with outra@rdmz.com.br work or school account."]',
                "valor": "",
            },
            {"tipo": "clicar", "seletor": 'input[name="idSIButton9"]', "valor": ""},
        ]
        session.learning_events = [
            {
                "step_index": 0,
                "event_type": "click",
                "selector": 'div[aria-label="Sign in with outra@rdmz.com.br work or school account."]',
                "url_before": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                "url_after": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                "title_before": "Sign in",
                "target_text": "Outra Pessoa",
                "target_label": "Sign in with outra@rdmz.com.br work or school account.",
                "source": "browser_recorder",
            },
            {
                "step_index": 1,
                "event_type": "click",
                "selector": 'input[name="idSIButton9"]',
                "url_before": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                "url_after": "https://nwcweb.randonconsorcios.com.br/CONAT/frmConAtCnsAtendimento.aspx",
                "title_before": "Permissions requested",
                "target_text": "Accept",
                "target_label": "Accept",
                "source": "browser_recorder",
            },
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session.save_learned_action", side_effect=lambda action_key, learned_action: captured.update({"acoes_conhecidas": {action_key: learned_action}})), patch(
            "backend.services.ai_observer.analyze_recorded_action_with_ai",
            new=AsyncMock(return_value=_review()),
        ):
            asyncio.run(manager.save_action("session", "Microsoft aprendido", "Consulta.", {}))
        action = captured["acoes_conhecidas"]["Microsoft aprendido"]  # type: ignore[index]
        self.assertEqual(action["passos_playwright"][0]["tipo"], "clicar")
        self.assertIn("login.microsoftonline.com", action["robust_steps"][0]["expected_url_before"])
        self.assertEqual(action["robust_steps"][0]["target_text"], "Outra Pessoa")
        self.assertEqual(action["robust_steps"][1]["target_text"], "Accept")


class OutputResultTests(unittest.TestCase):
    def test_run_keeps_deterministic_extraction(self) -> None:
        action = ActionDetail(
            id="consulta",
            key="Consulta",
            name="Consulta",
            description="",
            variables=[],
            steps_count=1,
            has_url=False,
            extraction_targets=["status"],
            ai_result_summary_enabled=False,
        )
        result = {
            "status": "success",
            "texto": "ok",
            "dados_extraidos": {"status": "Ativo"},
            "passos_executados": 1,
            "final_page": {"title": "Consulta", "url": "https://nwcweb.randonconsorcios.com.br/CONCP/consulta"},
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=result),
        ):
            run = asyncio.run(run_action_sync(action, ActionRunRequest()))
        self.assertEqual(run.result_payload["dados_extraidos"], {"status": "Ativo"})  # type: ignore[index]
        self.assertIn("Ativo", run.operational_summary or "")

    def test_runtime_file_metadata_and_file_summary(self) -> None:
        path = runtime_download_path("Relatorio", "unit-test-output")
        try:
            path.write_bytes(b"%PDF-" + b"0" * 2048)
            metadata = runtime_file_metadata(path)
            summary = asyncio.run(
                build_operational_summary(
                    {"output_type": "arquivo/PDF", "ai_result_summary_enabled": False},
                    status="success",
                    result_payload={"downloaded_files": [metadata], "main_file": metadata},
                )
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(metadata["mime_type"], "application/pdf")
        self.assertNotIn(str(path.parent), summary)
        self.assertEqual(summary, "Arquivo gerado com sucesso. Arquivo disponível.")

    def test_run_returns_safe_download_metadata(self) -> None:
        action = ActionDetail(
            id="relatorio",
            key="Relatorio",
            name="Relatório",
            description="",
            variables=[],
            steps_count=1,
            has_url=False,
            output_type="arquivo/PDF",
            ai_result_summary_enabled=False,
        )
        metadata = {
            "name": "relatorio.pdf",
            "path": "data/runs/downloads/run_relatorio.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 2048,
        }
        result = {
            "status": "success",
            "texto": "ok",
            "arquivos": [metadata["path"]],
            "downloaded_files": [metadata],
            "main_file": metadata,
            "passos_executados": 1,
            "final_page": {"title": "Relatório", "url": "https://nwcweb.randonconsorcios.com.br/CONCP/relatorio"},
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner._run_desktop_browser_replay",
            new=AsyncMock(return_value=result),
        ):
            run = asyncio.run(run_action_sync(action, ActionRunRequest()))
        self.assertEqual(run.result_payload["downloaded_files"], [metadata])  # type: ignore[index]
        self.assertEqual(run.result_payload["main_file"], metadata)  # type: ignore[index]
        self.assertEqual(run.operational_summary, "Arquivo gerado com sucesso. Arquivo disponível.")

    def test_disabled_ai_summary_never_calls_openai(self) -> None:
        llm = Mock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "not-used"}), patch(
            "backend.services.operational_summary.ChatOpenAI", llm
        ):
            summary = asyncio.run(
                build_operational_summary(
                    {"extraction_targets": ["status"], "ai_result_summary_enabled": False},
                    status="success",
                    result_payload={"dados_extraidos": {"status": "Ativo"}},
                )
            )
        llm.assert_not_called()
        self.assertIn("Ativo", summary)


if __name__ == "__main__":
    unittest.main()
