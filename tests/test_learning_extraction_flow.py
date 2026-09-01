from __future__ import annotations

import tests  # noqa: F401

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.db import Run as DbRun, SessionLocal
from backend.schemas.runs import RunRecord
from backend.services.actions_repository import save_learned_action
from backend.services.result_selection import (
    build_extraction_contract,
    detect_extraction_candidates,
    extract_with_contract,
    normalize_extracted_value,
    validate_candidate_value,
)
from backend.services.runs_repository import append_run
from tests.auth_helpers import authenticated_client


def _run_payload() -> dict[str, object]:
    return {
        "id": "run-032",
        "action_id": "quantidade-de-parcelas",
        "action_key": "Quantidade de parcelas",
        "status": "success",
        "mode": "sync",
        "run_type": "action_run",
        "requested_by": "test",
        "created_at": "2026-07-09T00:00:00+00:00",
        "started_at": "2026-07-09T00:00:00+00:00",
        "finished_at": "2026-07-09T00:00:01+00:00",
        "variables": {"grupo": "935"},
        "operational_summary": "032",
        "result_payload": {
            "dados_extraidos": {"Qtd. Pcls. Pagas": "032"},
            "final_page_dom": "<table><tr><td>Qtd. Pcls. Pagas</td><td>032</td></tr></table>",
            "final_page_text": "Qtd. Pcls. Pagas\n032",
        },
    }


class LearningExtractionFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        with SessionLocal.begin() as session:
            session.query(DbRun).filter(DbRun.action_id == "quantidade-de-parcelas").delete()

    def test_confirm_last_result_saves_extraction_review_and_preserves_zero(self) -> None:
        raw_action = {
            "nome_amigavel": "Quantidade de parcelas",
            "browser_mode": "desktop_browser",
            "passos_playwright": [{"tipo": "clicar", "seletor": "#consultar"}],
            "robust_steps": [{"tipo": "clicar", "seletor": "#consultar"}],
            "extraction_target": "Qtd. Pcls. Pagas",
            "extraction_targets": ["Qtd. Pcls. Pagas"],
        }
        save_learned_action("Quantidade de parcelas", raw_action)
        append_run(RunRecord(**_run_payload()))
        with authenticated_client() as client:
            response = client.post(
                "/api/actions/quantidade-de-parcelas/extraction/confirm-last-result",
                json={"target_name": "Quantidade de parcelas", "screen_label": "Qtd. Pcls. Pagas"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["detected_result"]["value"], "032")
        self.assertEqual(body["extraction_review"]["expected_example"], "032")
        self.assertEqual(body["extraction_review"]["screen_label"], "Qtd. Pcls. Pagas")
        self.assertIn("Retorne somente", body["reviewed_overlay"]["summary_instruction"])

    def test_test_saved_extraction_returns_ok_for_valid_value(self) -> None:
        raw_action = {
            "nome_amigavel": "Quantidade de parcelas",
            "browser_mode": "desktop_browser",
            "passos_playwright": [{"tipo": "clicar", "seletor": "#consultar"}],
            "extraction_review": {
                "source": "visual_result_selection",
                "target_name": "Quantidade de parcelas",
                "screen_label": "Qtd. Pcls. Pagas",
                "selection_type": "field_value",
                "value_type": "integer",
                "avoid_labels": ["Ocorrência"],
            },
        }
        save_learned_action("Quantidade de parcelas", raw_action)
        append_run(RunRecord(**_run_payload()))
        with authenticated_client() as client:
            response = client.post("/api/actions/quantidade-de-parcelas/extraction/test")

        self.assertEqual(response.status_code, 200)
        extraction_test = response.json()["extraction_test"]
        self.assertEqual(extraction_test["status"], "ok")
        self.assertEqual(extraction_test["value"], "032")

    def test_detector_ignores_css_and_technical_dom_text(self) -> None:
        html = """
        <head><style>.grid{max-width:400px;} /* IE7+, FF, WebKit(Chrome, Safari) */</style></head>
        <body><table><tr><td>Qtd. Pcls. Pagas</td><td>038</td></tr></table></body>
        """
        candidates = detect_extraction_candidates(html, target_name="quantidade de parcelas", screen_label="Qtd. Pcls. Pagas")
        rendered = " ".join(f"{item.get('label')} {item.get('value')}" for item in candidates)

        self.assertIn("038", rendered)
        self.assertNotIn("max-width", rendered)
        self.assertNotIn("WebKit", rendered)
        self.assertNotIn("Chrome", rendered)

    def test_confirmed_locator_contract_returns_zero_padded_values(self) -> None:
        contract = build_extraction_contract(
            target_name="Qtd. Pcls. Pagas",
            screen_label="Qtd. Pcls. Pagas",
            candidate={
                "selected_element": {
                    "selector": "#ctl00_Conteudo_lblQT_Pcls_Paga",
                    "tag_name": "span",
                    "label": "Qtd. Pcls. Pagas",
                    "nearby_text": "Qtd. Pcls. Pagas:",
                    "value": "040",
                },
                "normalization": "digits_only",
                "value_type": "integer",
            },
            selection_type="field_value",
        )

        self.assertEqual(contract["example_value"], "040")
        self.assertEqual(contract["selector_data"]["primary"], "#ctl00_Conteudo_lblQT_Pcls_Paga")
        self.assertEqual(contract["normalization"], {"type": "digits_only"})
        for value in ("040", "027", "005"):
            html = f'<span id="ctl00_Conteudo_lblQT_Pcls_Paga">Qtd. Pcls. Pagas: {value}</span>'
            result = extract_with_contract(html, "", contract)
            self.assertEqual(result["value"], value)

    def test_exact_visual_selector_wins_over_noisy_neighboring_context(self) -> None:
        contract = {
            "target_name": "O número de parcelas",
            "screen_label": "Dif. Grupo: 0 0,0000 Qtd. Pcls. Pagas:",
            "selection_type": "block_text",
            "value_type": "decimal_percent",
            "normalization": {"type": "digits_only"},
            "selector_data": {"primary": "#ctl00_Conteudo_lblQT_Pcls_Paga"},
        }
        html_template = """
        {prefix}
        <div>0 | 0,0000 | Qtd. Pcls. Pagas: |
          <span id="ctl00_Conteudo_lblQT_Pcls_Paga">{value}</span> |
          Qtd. Pcls. Furo: | 000 | Lance Mín: 0,0000%
        </div>
        """
        for expected in ("034", "027", "005"):
            result = extract_with_contract(html_template.format(prefix="x" * 60000, value=expected), "", contract)
            self.assertEqual(result["value"], expected)
            self.assertFalse(result["needs_attention"])
            self.assertEqual(result["source"], "visual_contract_selector")

    def test_invalid_candidate_cannot_be_saved_as_success(self) -> None:
        empty = build_extraction_contract(
            target_name="Quantidade de parcelas",
            screen_label="Qtd. Pcls. Pagas",
            candidate={"label": "Qtd. Pcls. Pagas", "value": "", "type": "field_value"},
        )
        occurrence = validate_candidate_value("Ocorrência", "decimal_percent")

        self.assertTrue(empty["needs_attention"])
        self.assertFalse(empty["validation"]["valid"])
        self.assertTrue(occurrence["needs_attention"])
        self.assertFalse(occurrence["valid"])

    def test_digits_only_preserves_leading_zeroes(self) -> None:
        self.assertEqual(normalize_extracted_value("040", "digits_only")["value"], "040")
        self.assertEqual(normalize_extracted_value("Qtd: 040", "digits_only")["value"], "040")
        self.assertEqual(normalize_extracted_value("ABC 00123", "digits_only")["value"], "00123")

    def test_digits_only_requires_explicit_group_when_multiple_numbers_exist(self) -> None:
        result = normalize_extracted_value("12 de 040", "digits_only")

        self.assertTrue(result["needs_attention"])
        self.assertEqual(result["reason"], "multiple_numeric_groups")

    def test_contract_keeps_visual_value_as_example_not_primary_locator(self) -> None:
        contract = build_extraction_contract(
            target_name="Quantidade de parcelas",
            screen_label="Qtd. Pcls. Pagas",
            candidate={
                "label": "Qtd. Pcls. Pagas",
                "value": "040",
                "type": "field_value",
                "normalization": "digits_only",
                "selector": "#parcelas-pagas",
            },
        )
        result = extract_with_contract(
            "<div><span>Qtd. Pcls. Pagas:</span> <span id='parcelas-pagas'>041</span></div>",
            "",
            contract,
        )

        self.assertEqual(contract["expected_example"], "040")
        self.assertNotIn("040", contract["selector_data"]["primary"])
        self.assertEqual(result["value"], "041")
        self.assertFalse(result["needs_attention"])

    def test_contract_extracts_adjacent_label_value_when_value_changes(self) -> None:
        contract = build_extraction_contract(
            target_name="Quantidade de parcelas",
            screen_label="Qtd. Pcls. Pagas",
            candidate={
                "label": "Qtd. Pcls. Pagas",
                "value": "040",
                "type": "field_value",
                "normalization": "digits_only",
            },
        )
        result = extract_with_contract(
            "<div><label>Qtd. Pcls. Pagas</label><span>041</span></div>",
            "",
            contract,
        )

        self.assertEqual(result["value"], "041")
        self.assertFalse(result["needs_attention"])

    def test_password_input_candidate_is_rejected(self) -> None:
        contract = build_extraction_contract(
            target_name="Senha",
            screen_label="Senha",
            candidate={
                "label": "Senha",
                "value": "segredo",
                "type": "block_text",
                "tag_name": "input",
                "input_type": "password",
                "read_mode": "value",
            },
        )

        self.assertTrue(contract["needs_attention"])
        self.assertEqual(contract["validation"]["reason"], "password_field")

    def test_input_value_contract_records_value_read_mode(self) -> None:
        contract = build_extraction_contract(
            target_name="Quantidade de parcelas",
            screen_label="Qtd. Pcls. Pagas",
            candidate={
                "label": "Qtd. Pcls. Pagas",
                "value": "040",
                "type": "field_value",
                "tag_name": "input",
                "input_type": "text",
                "read_mode": "value",
                "normalization": "digits_only",
            },
        )

        self.assertFalse(contract["needs_attention"])
        self.assertEqual(contract["read_mode"], "value")
        self.assertEqual(contract["expected_example"], "040")

    def test_locator_failure_does_not_capture_neighbor_field(self) -> None:
        result = extract_with_contract(
            "<div><span>Saldo:</span> <span>999</span></div>",
            "",
            {
                "source": "visual_result_selection",
                "target_name": "Quantidade de parcelas",
                "screen_label": "Qtd. Pcls. Pagas",
                "selection_type": "field_value",
                "normalization": {"type": "digits_only"},
            },
        )

        self.assertEqual(result["value"], "")
        self.assertTrue(result["needs_attention"])
        self.assertEqual(result["validation"]["reason"], "locator_not_found")

    def test_learning_result_selection_v1_endpoints_return_operator_preview(self) -> None:
        with authenticated_client() as client, patch(
            "backend.api.v1.demo_session_manager.start_result_selection",
            new=AsyncMock(return_value={"status": "active"}),
        ), patch(
            "backend.api.v1.demo_session_manager.capture_result_selection",
            new=AsyncMock(
                return_value={
                    "status": "captured",
                    "captured": {"selected_text": "040"},
                    "candidates": [{"label": "Qtd. Pcls. Pagas", "value": "040", "type": "field_value"}],
                }
            ),
        ), patch(
            "backend.api.v1.demo_session_manager.confirm_result_selection",
            new=AsyncMock(
                return_value={
                    "status": "confirmed",
                    "extraction_review": {
                        "screen_label": "Qtd. Pcls. Pagas",
                        "expected_example": "040",
                        "normalization": {"type": "digits_only"},
                    },
                }
            ),
        ):
            started = client.post("/api/v1/learning/sessions/session/result-selection/start")
            captured = client.post(
                "/api/v1/learning/sessions/session/result-selection/capture",
                json={"target_name": "Quantidade", "screen_label": "Qtd. Pcls. Pagas"},
            )
            confirmed = client.post(
                "/api/v1/learning/sessions/session/result-selection/confirm",
                json={
                    "target_name": "Quantidade",
                    "screen_label": "Qtd. Pcls. Pagas",
                    "selection_type": "field_value",
                    "candidate": {"label": "Qtd. Pcls. Pagas", "value": "040", "type": "field_value"},
                    "normalization": "digits_only",
                },
            )

        self.assertEqual(started.status_code, 200)
        self.assertEqual(captured.json()["candidates"][0]["value"], "040")
        self.assertEqual(confirmed.json()["extraction_review"]["expected_example"], "040")


if __name__ == "__main__":
    unittest.main()
