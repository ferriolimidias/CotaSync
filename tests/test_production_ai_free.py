from __future__ import annotations

import ast
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.services.operational_summary import build_operational_summary_result


ROOT = Path(__file__).resolve().parents[1]


class ProductionAIFreeTests(unittest.TestCase):
    def _assert_modules_are_ai_free(self, *relative_modules: str) -> None:
        forbidden = ("ChatOpenAI", "acompletion", "LearningAIObserver", "analyze_recorded_action_with_ai")
        for relative in relative_modules:
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names
            }
            self.assertTrue(names.isdisjoint(forbidden), relative)
            self.assertTrue(imported.isdisjoint(forbidden), relative)

    def test_operational_summary_never_calls_provider(self) -> None:
        fake_provider = AsyncMock()
        with patch("backend.services.operational_summary.deterministic_operational_summary", return_value="ok"), patch(
            "backend.services.operational_summary._metadata", return_value=True
        ):
            result = asyncio.run(
                build_operational_summary_result(
                    {"name": "fixture", "ai_result_summary_enabled": True},
                    status="success",
                    result_payload={"dados_extraidos": {"result": "040"}},
                )
            )
        fake_provider.assert_not_called()
        self.assertEqual(result.summary_source, "deterministic")
        self.assertFalse(result.ai_summary_used)

    def test_runtime_modules_have_no_direct_provider_call_sites(self) -> None:
        runtime_modules = (
            "backend/services/operational_summary.py",
            "backend/services/action_validation_review.py",
            "backend/services/action_runner.py",
            "backend/services/batch_runner.py",
            "backend/services/google_sync_queue.py",
        )
        self._assert_modules_are_ai_free(*runtime_modules)

    def test_individual_replay_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/action_runner.py", "backend/services/operational_summary.py")

    def test_batch_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/batch_runner.py")

    def test_retry_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/action_runner.py", "backend/services/batch_runner.py")

    def test_resume_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/batch_runner.py")

    def test_access_bootstrap_replay_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/action_runner.py")

    def test_google_sync_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/google_sync_queue.py")

    def test_operational_summary_ai_zero(self) -> None:
        self._assert_modules_are_ai_free("backend/services/operational_summary.py")

    def test_legacy_replay_does_not_auto_heal_with_ai(self) -> None:
        from backend import agente

        with patch.object(agente, "carregar_ui_map", return_value={"acoes_conhecidas": {"fixture": {"passos_playwright": []}}}), patch(
            "backend.agente.executar_acao_rapida", new=AsyncMock(side_effect=RuntimeError("replay failed"))
        ), patch.object(agente, "acionar_ia_cartografa", new=AsyncMock()) as ai_mapper:
            result = asyncio.run(agente.executar_acao_desktop_replay("fixture"))
        ai_mapper.assert_not_awaited()
        self.assertEqual(result["status"], "error")

    def test_legacy_chat_fallback_is_deterministic(self) -> None:
        from backend import agente

        with patch.object(agente, "_criar_llm", side_effect=AssertionError("AI must not run")):
            result = asyncio.run(agente.executar_agente("resuma a execução"))
        self.assertEqual(result["status"], "deterministic_only")


if __name__ == "__main__":
    unittest.main()
