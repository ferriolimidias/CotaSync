from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest
from backend.services.action_runner import run_action_sync
from backend.services.operational_summary import (
    build_operational_summary,
    deterministic_operational_summary,
)


def _action(**overrides: object) -> dict[str, object]:
    action: dict[str, object] = {
        "nome_amigavel": "Consultar cliente",
        "objective": "Consultar o cadastro do cliente",
        "expected_result": "Retornar o status do cliente",
        "extraction_targets": ["status_cliente"],
        "ai_result_summary_enabled": True,
        "passos_playwright": [
            {"tipo": "extrair_texto", "seletor": "#status-interno", "nome": "status_cliente"}
        ],
    }
    action.update(overrides)
    return action


class OperationalSummaryTests(unittest.TestCase):
    def test_action_with_extraction_returns_extracted_value(self) -> None:
        summary = deterministic_operational_summary(
            _action(),
            status="success",
            result_payload={"dados_extraidos": {"status_cliente": "Ativo"}},
        )
        self.assertIn("Ativo", summary)
        self.assertNotIn("#status-interno", summary)

    def test_action_without_extraction_reports_missing_final_result(self) -> None:
        summary = deterministic_operational_summary(
            _action(extraction_targets=[], passos_playwright=[]),
            status="success",
            result_payload={},
        )
        self.assertEqual(
            summary,
            "Ação executada com sucesso, mas nenhum resultado final foi configurado para retorno.",
        )

    def test_fallback_works_without_openai_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            summary = asyncio.run(
                build_operational_summary(
                    _action(),
                    status="success",
                    result_payload={"dados_extraidos": {"status_cliente": "Ativo"}},
                )
            )
        self.assertIn("Ativo", summary)

    def test_page_only_success_uses_stable_operational_summary(self) -> None:
        summary = asyncio.run(
            build_operational_summary(
                _action(extraction_targets=[], passos_playwright=[]),
                status="success",
                result_payload={"final_page": {"title": "Intranet Newcon"}},
            )
        )
        self.assertEqual(
            summary,
            "Ação executada com sucesso. A tela solicitada foi aberta, mas nenhum dado foi configurado para extração.",
        )

    def test_reauthentication_summary_is_stable(self) -> None:
        summary = asyncio.run(
            build_operational_summary(
                _action(),
                status="error",
                error_message="A sessao precisa ser autenticada novamente.",
            )
        )
        self.assertEqual(
            summary,
            "Não consegui executar a ação porque a sessão precisa ser autenticada novamente.",
        )

    def test_ai_output_with_technical_or_secret_content_is_rejected(self) -> None:
        fake_llm = SimpleNamespace(
            ainvoke=AsyncMock(return_value=SimpleNamespace(content="desktop_browser selector #interno token segredo"))
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "backend.services.operational_summary.ChatOpenAI", return_value=fake_llm
        ):
            summary = asyncio.run(
                build_operational_summary(
                    _action(),
                    status="success",
                    result_payload={
                        "dados_extraidos": {
                            "#status-interno": "Ativo",
                            "access_token": "credencial-super-secreta",
                        }
                    },
                )
            )
        lowered = summary.casefold()
        self.assertIn("ativo", lowered)
        self.assertNotIn("desktop_browser", lowered)
        self.assertNotIn("selector", lowered)
        self.assertNotIn("credencial-super-secreta", lowered)

    def test_quick_execution_chat_uses_operational_summary(self) -> None:
        from backend import agente

        raw_action = _action()
        execution = {
            "status": "sucesso",
            "evidencia": "evidence.png",
            "arquivos_baixados": [],
            "dados_extraidos": {"status_cliente": "Ativo"},
            "passos_executados": 1,
            "final_page": {"title": "Cadastro", "url": "https://example.test/cadastro"},
        }
        with patch.dict(os.environ, {}, clear=True), patch.object(
            agente, "carregar_ui_map", return_value={"acoes_conhecidas": {"Consultar cliente": raw_action}}
        ), patch.object(agente, "executar_acao_rapida", new=AsyncMock(return_value=execution)):
            response = asyncio.run(agente.executar_acao_fast_track("Consultar cliente"))

        self.assertEqual(response["texto"], response["operational_summary"])
        self.assertIn("Ativo", response["texto"])
        self.assertNotIn("Execução rápida concluída com sucesso da memória", response["texto"])

    def test_run_keeps_technical_details_out_of_operational_summary(self) -> None:
        action = ActionDetail(
            id="consultar-cliente",
            key="Consultar cliente",
            name="Consultar cliente",
            description="Consulta um cliente.",
            objective="Consultar o cadastro do cliente",
            expected_result="Retornar o status",
            extraction_targets=["status_cliente"],
            variables=[],
            steps_count=1,
            has_url=True,
        )
        execution = {
            "status": "success",
            "texto": "execução técnica concluída",
            "dados_extraidos": {"status_cliente": "Ativo"},
            "passos_executados": 1,
            "selector_diagnostics": [{"selector": "#status-interno", "visible": True}],
        }
        with patch.dict(os.environ, {}, clear=True), patch(
            "backend.services.action_runner.append_run"
        ), patch("backend.services.action_runner.update_run"), patch(
            "backend.services.action_runner.executar_acao_fast_track",
            new=AsyncMock(return_value=execution),
        ):
            run = asyncio.run(run_action_sync(action, ActionRunRequest()))

        self.assertEqual(run.status, "success")
        self.assertIn("Ativo", run.operational_summary or "")
        self.assertNotIn("#status-interno", run.operational_summary or "")
        self.assertIn("#status-interno", str(run.result_payload))
        self.assertIn("diagnósticos=1", run.technical_summary or "")


if __name__ == "__main__":
    unittest.main()
