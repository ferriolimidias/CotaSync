from __future__ import annotations

import asyncio
import os
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest
from backend.services.action_runner import run_action_sync
from backend.services.operational_summary import (
    build_operational_summary,
    build_operational_summary_result,
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

    def test_noisy_extracted_text_becomes_concise_deterministic_summary(self) -> None:
        noisy = (
            "Página Inicial Venda Grupo Cobrança Relatórios Página Inicial Venda Grupo Cobrança "
            "Filtros Consulta Grupo Produto Situação Período Tipo de venda " * 25
        )
        summary = deterministic_operational_summary(
            _action(extraction_targets=["texto_tela_final"]),
            status="success",
            result_payload={"dados_extraidos": {"texto_tela_final": noisy}},
        )
        self.assertLess(len(summary), 260)
        self.assertNotIn("Página Inicial Venda Grupo Cobrança Relatórios Página Inicial", summary)

    def test_form_filter_page_is_not_reported_as_final_result(self) -> None:
        text = (
            "Página Inicial\nVenda\nGrupo\nCobrança\nRelatórios\n"
            "Consulta de relatório\nGrupo\nPeríodo\nProduto\nTipo de venda\nSituação\nConsultar"
        )
        summary = deterministic_operational_summary(
            _action(extraction_targets=["texto_tela_final"]),
            status="success",
            result_payload={"dados_extraidos": {"texto_tela_final": text * 10}},
        )
        lowered = summary.casefold()
        self.assertIn("formulário", lowered)
        self.assertTrue("nenhum resultado listado" in lowered or "nenhum resultado específico" in lowered)
        self.assertNotIn("encontrei: texto tela final", lowered)

    def test_real_full_page_report_text_gets_operational_summary(self) -> None:
        text = (
            "Página Inicial Venda Grupo Cobrança Contemplação Crédito Encerramento Sistema Atendimento "
            "Pré-Contemplação Contemplação Relatório Bens a Entregar Voltar Posição Atual Posição "
            "Contábil Data Base: Lista apenas entregas Parciais Considera os lançamentos de pagamento "
            "de bem embutido, como entrega de bem parcial Considera os lançamentos de pagamento de bem "
            "com FGTS, como entrega de bem parcial Contemplação Sorteio Contemplação Lance Lista somente "
            "Lances Pagos Intervalo Inicial Final Grupo Sit. do Grupo Produto Tipo de Venda Ponto de "
            "Venda Inicial Final Agrupamento Filial Unidade Negócio Comissionado Inicial Final Ponto "
            "Entrega Contemplação Percentual Pago Bem Ordem GrupoPonto de EntregaPonto de Venda "
            "FilialUnidade Negócio Salta de Página por Grupo Considerar situação grupo na data base "
            "informada Considera as cotas canceladas Considera as cotas com lance parcelado pendente"
        )
        summary = deterministic_operational_summary(
            _action(extraction_targets=["texto_tela_final"]),
            status="success",
            result_payload={"dados_extraidos": {"texto_tela_final": text}},
        )
        lowered = summary.casefold()
        self.assertTrue("relatório de bens a entregar" in lowered or "relatório" in lowered)
        self.assertIn("data base", lowered)
        self.assertIn("grupo", lowered)
        self.assertIn("produto", lowered)
        self.assertIn("tipo de venda", lowered)
        self.assertTrue("nenhum resultado listado" in lowered or "aguardando filtros" in lowered)
        self.assertNotIn("não foi possível identificar", lowered)
        self.assertNotIn("Página Inicial Venda Grupo Cobrança Contemplação Crédito", summary)
        self.assertLess(len(summary), 500)

    def test_real_extracted_fields_are_summarized_clearly(self) -> None:
        summary = deterministic_operational_summary(
            _action(extraction_targets=["cliente", "grupo", "cota", "status"]),
            status="success",
            result_payload={
                "dados_extraidos": {
                    "cliente": "João Silva",
                    "grupo": "123",
                    "cota": "456",
                    "status": "Ativo",
                }
            },
        )
        self.assertIn("João Silva", summary)
        self.assertIn("Grupo: 123", summary)
        self.assertIn("Cota: 456", summary)
        self.assertIn("Status: Ativo", summary)

    def test_downloaded_file_summary_mentions_available_file(self) -> None:
        metadata = {
            "name": "relatorio.pdf",
            "path": "data/runs/downloads/run-1/relatorio.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 12,
        }
        summary = deterministic_operational_summary(
            _action(extraction_targets=[], passos_playwright=[], output_type="arquivo/PDF"),
            status="success",
            result_payload={"downloaded_files": [metadata], "main_file": metadata},
        )
        self.assertIn("Arquivo disponível", summary)

    def test_missing_valor_parcela_target_has_specific_summary(self) -> None:
        summary = deterministic_operational_summary(
            _action(
                objective="Consultar valor da parcela atual",
                extraction_targets=["valor_da_parcela_atual"],
            ),
            status="success",
            result_payload={"dados_extraidos": {"valor_da_parcela_atual": ""}},
        )
        self.assertEqual(
            summary,
            "A ação foi executada, mas não encontrei o valor da parcela atual na tela final.",
        )

    def test_qtd_pcls_pagas_target_returns_precise_value_and_not_found_message(self) -> None:
        summary = deterministic_operational_summary(
            _action(
                objective="Consultar quantidade de parcelas pagas",
                extraction_targets=["Qtd. Pcls. Pagas"],
            ),
            status="success",
            result_payload={"dados_extraidos": {"Qtd. Pcls. Pagas": "032"}},
        )
        self.assertEqual(summary, "Quantidade de parcelas pagas: 032")

        not_found = deterministic_operational_summary(
            _action(
                objective="Consultar quantidade de parcelas pagas",
                extraction_targets=["Qtd. Pcls. Pagas"],
            ),
            status="success",
            result_payload={"dados_extraidos": {"Qtd. Pcls. Pagas": ""}},
        )
        self.assertEqual(
            not_found,
            "A ação foi executada, mas não encontrei o campo Qtd. Pcls. Pagas na tela final.",
        )

    def test_timeout_with_step_diagnostics_has_actionable_summary(self) -> None:
        summary = deterministic_operational_summary(
            _action(),
            status="error",
            error_message="timeout esperando expected_selector_after",
            result_payload={"step_diagnostics": [{"result": "timeout", "step_index": 1}]},
        )
        self.assertEqual(
            summary,
            "Não consegui concluir a ação porque o sistema demorou para abrir a próxima tela. "
            "Tente novamente ou reautentique a sessão se necessário.",
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

    def test_openai_error_falls_back_deterministically(self) -> None:
        fake_llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("offline")))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "backend.services.operational_summary.ChatOpenAI", return_value=fake_llm
        ):
            result = asyncio.run(
                build_operational_summary_result(
                    _action(),
                    status="success",
                    result_payload={"dados_extraidos": {"status_cliente": "Ativo"}},
                )
            )
        self.assertEqual(result.summary_source, "deterministic")
        self.assertFalse(result.ai_summary_used)
        self.assertIn("Ativo", result.summary)

    def test_ai_disabled_does_not_call_openai(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True), patch(
            "backend.services.operational_summary.ChatOpenAI"
        ) as chat_openai:
            result = asyncio.run(
                build_operational_summary_result(
                    _action(ai_result_summary_enabled=False),
                    status="success",
                    result_payload={"dados_extraidos": {"status_cliente": "Ativo"}},
                )
            )
        chat_openai.assert_not_called()
        self.assertEqual(result.summary_source, "deterministic")

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

    def test_ai_summary_uses_limited_sanitized_context(self) -> None:
        fake_llm = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=SimpleNamespace(
                    content="Consulta concluída. A tela aberta parece ser um formulário de relatório/filtro. Nenhum resultado específico foi listado ainda."
                )
            )
        )
        noisy = (
            "Página Inicial Venda Grupo Cobrança Relatórios token=abc123 "
            "/opt/cotasync-test/src/data/runs/downloads/secret.pdf "
            "Grupo Período Produto Tipo de venda Situação Consultar " * 400
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "cheap-model"}, clear=True), patch(
            "backend.services.operational_summary.ChatOpenAI", return_value=fake_llm
        ) as chat_openai:
            result = asyncio.run(
                build_operational_summary_result(
                    _action(extraction_targets=["texto_tela_final"]),
                    status="success",
                    result_payload={"dados_extraidos": {"texto_tela_final": noisy}},
                )
            )
        prompt = fake_llm.ainvoke.await_args.args[0]
        self.assertEqual(result.summary_source, "ai")
        self.assertTrue(result.ai_summary_used)
        self.assertLess(len(prompt), 9500)
        self.assertNotIn("abc123", prompt)
        self.assertNotIn("/opt/cotasync-test", prompt)
        chat_openai.assert_called_once()

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
        self.assertEqual(run.summary_source, "deterministic")
        self.assertEqual(run.summary_reason, "openai_api_key_missing")
        self.assertFalse(run.ai_summary_used)

    def test_operational_summary_does_not_leak_selectors_tokens_credentials_or_paths(self) -> None:
        summary = deterministic_operational_summary(
            _action(extraction_targets=["status"]),
            status="success",
            result_payload={
                "dados_extraidos": {
                    "#status-interno": "Ativo",
                    "access_token": "sk-secret",
                    "senha": "123456",
                    "arquivo": "/opt/cotasync-test/src/data/runs/downloads/boleto.pdf",
                }
            },
        )
        self.assertNotIn("#status-interno", summary)
        self.assertNotIn("sk-secret", summary)
        self.assertNotIn("123456", summary)
        self.assertNotIn("/opt/cotasync-test", summary)

    def test_frontend_chat_keeps_raw_extracted_data_in_expander(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "frontend" / "app.py").read_text(encoding="utf-8")
        self.assertIn('st.expander("Ver dados extraídos", expanded=False)', source)
        self.assertIn('st.expander("Ver diagnóstico técnico", expanded=False)', source)
        self.assertIn('st.expander("Ver JSON/result_payload", expanded=False)', source)
        self.assertNotIn('st.write("Textos / dados extraídos nesta execução:")', source)

    def test_frontend_quick_execution_uses_friendly_variable_labels_and_runs_api(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "frontend" / "app.py").read_text(encoding="utf-8")
        self.assertIn("_rotulo_variavel(variable)", source)
        self.assertIn('f"/api/actions/{action_id}/run"', source)
        self.assertIn('"requested_by": "streamlit-quick"', source)

    def test_frontend_objective_extraction_mentions_parcela_targets(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "frontend" / "app.py").read_text(encoding="utf-8")
        self.assertIn("Qtd. Pcls. Pagas", source)
        self.assertIn("O que esta rotina deve retornar?", source)
        self.assertIn("Digitar nome do campo desejado", source)


if __name__ == "__main__":
    unittest.main()
