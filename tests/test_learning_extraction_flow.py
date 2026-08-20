from __future__ import annotations

import tests  # noqa: F401

import json
import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend.db import Run as DbRun, SessionLocal
from backend.schemas.runs import RunRecord
from backend.services.actions_repository import save_learned_action
from backend.services.result_selection import (
    build_extraction_contract,
    detect_extraction_candidates,
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


if __name__ == "__main__":
    unittest.main()
