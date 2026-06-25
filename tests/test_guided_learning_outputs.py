from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest
from backend.services.action_runner import run_action_sync
from backend.services.actions_repository import load_actions_catalog
from backend.services.demo_session import DemoSessionManager
from backend.services.external_systems import load_current_external_system
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

    async def screenshot(self, **_kwargs: object) -> None:
        return None


class FakeLocator:
    async def fill(self, _value: str, **_kwargs: object) -> None:
        return None

    async def evaluate(self, *_args: object, **_kwargs: object) -> None:
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
        download_detected=download_detected,
        recording=True,
        status="gravando",
        operator_recording_suppressed_until=0.0,
        browser_mode="browserless",
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
    def test_default_access_profile_exists_for_demo_external_system(self) -> None:
        config = load_current_external_system()
        self.assertEqual(config["access_profile_name"], "Priscila")
        self.assertEqual(config["microsoft_saved_account_text"], "Priscila Susin")
        self.assertEqual(config["microsoft_saved_account_identifier"], "D0004267@rdmz.com.br")
        self.assertEqual(config["expected_system_host"], "nwcweb.randonconsorcios.com.br")
        self.assertIn("m365.cloud.microsoft", config["microsoft_hosts"])

    def test_guided_metadata_and_extraction_are_saved_and_sent_to_synthesis(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}

        def save(payload: dict[str, object]) -> None:
            captured.update(payload)

        analyzer = AsyncMock(return_value=_review())
        with patch("backend.services.demo_session._load_ui_map", return_value={"acoes_conhecidas": {}}), patch(
            "backend.services.demo_session._save_ui_map", side_effect=save
        ), patch("backend.services.ai_observer.analyze_recorded_action_with_ai", analyzer):
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

    def test_download_detected_action_converts_click_to_file_output(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _session(download_detected=True)  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session._load_ui_map", return_value={"acoes_conhecidas": {}}), patch(
            "backend.services.demo_session._save_ui_map", side_effect=lambda payload: captured.update(payload)
        ), patch(
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

    def test_variable_names_are_suggested_as_friendly_schema_and_renamable(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [
            {"tipo": "preencher", "seletor": "#ctl00_Conteudo_edtGrupo", "valor": ""},
            {"tipo": "preencher", "seletor": "#ctl00_Conteudo_edtCota", "valor": ""},
            {"tipo": "preencher", "seletor": "select:nth-of-type(1)", "valor": ""},
        ]
        session.learning_events = [
            {"step_index": 0, "event_type": "fill", "selector": "#ctl00_Conteudo_edtGrupo"},
            {"step_index": 1, "event_type": "fill", "selector": "#ctl00_Conteudo_edtCota"},
            {"step_index": 2, "event_type": "fill", "selector": "select:nth-of-type(1)"},
        ]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session._load_ui_map", return_value={"acoes_conhecidas": {}}), patch(
            "backend.services.demo_session._save_ui_map", side_effect=lambda payload: captured.update(payload)
        ), patch(
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
        self.assertEqual([item["key"] for item in saved["variables"]], ["grupo", "cota", "tipo_consulta"])

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
            result = asyncio.run(manager.operator_fill("session", "#ctl00_Conteudo_edtGrupo", "123", record_action=True))
        self.assertTrue(result["recorded"])
        raw_event = recorder.await_args.args[1]
        self.assertEqual(raw_event["tipo"], "preencher")
        self.assertEqual(raw_event["event_type"], "fill")
        self.assertEqual(raw_event["seletor"], "#ctl00_Conteudo_edtGrupo")
        self.assertEqual(raw_event["value_template"], "{{input_value}}")

    def test_missing_expected_input_capture_is_persisted_as_warning(self) -> None:
        manager = DemoSessionManager()
        session = _session()  # type: ignore[assignment]
        session.steps = [{"tipo": "clicar", "seletor": "#buscar", "valor": ""}]
        session.learning_events = [{"step_index": 0, "event_type": "click", "selector": "#buscar"}]
        manager._sessions["session"] = session  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session._load_ui_map", return_value={"acoes_conhecidas": {}}), patch(
            "backend.services.demo_session._save_ui_map", side_effect=lambda payload: captured.update(payload)
        ), patch(
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

    def test_external_learned_action_saves_access_profile_metadata(self) -> None:
        manager = DemoSessionManager()
        manager._sessions["session"] = _external_session()  # type: ignore[attr-defined]
        captured: dict[str, object] = {}
        with patch("backend.services.demo_session._load_ui_map", return_value={"acoes_conhecidas": {}}), patch(
            "backend.services.demo_session._save_ui_map", side_effect=lambda payload: captured.update(payload)
        ), patch(
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
            "final_page": {"title": "Consulta", "url": "https://example.test"},
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner.executar_acao_fast_track",
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
            "final_page": {"title": "Relatório", "url": "https://example.test"},
        }
        with patch("backend.services.action_runner.append_run"), patch(
            "backend.services.action_runner.update_run"
        ), patch(
            "backend.services.action_runner.executar_acao_fast_track",
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
