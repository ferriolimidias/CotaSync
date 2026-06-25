from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest
from backend.services.action_runner import run_action_sync
from backend.services.demo_session import DemoSessionManager
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


def _session(*, download_detected: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
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
        browser_mode="browserless",
        external_system_name="",
        external_login_url="",
        page=FakePage(),
    )


class GuidedLearningSaveTests(unittest.TestCase):
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
        self.assertEqual([item["key"] for item in saved["variables"]], ["grupo", "cota", "tipo_consulta"])


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
