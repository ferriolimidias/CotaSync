from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.ai_observer import (
    _safe_action,
    analyze_recorded_action_with_ai,
    learning_ai_analysis_contract,
    validate_ai_review_suggestions,
)
from backend.services.demo_session import DemoSessionManager
from backend.services.learning_session_store import learning_evidence_fingerprint
from backend.services.learning_trace import build_raw_learning_trace


def _action() -> dict:
    return {
        "nome_amigavel": "Fixture review",
        "objective": "Consultar um resultado",
        "expected_result": "040",
        "url_inicial": "https://example.test/page?oauth_code=secret",
        "passos_playwright": [
            {"tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"},
            {"tipo": "preencher", "seletor": "#versao", "variavel": "versao"},
            {"tipo": "extrair_texto", "seletor": "#resultado", "nome": "parcelas"},
        ],
        "learning_events": [
            {"event_type": "fill", "selector": "#grupo", "url_before": "https://example.test/?token=hidden"},
        ],
        "output_candidates": [{"selector": "#resultado", "label": "Parcelas", "preview": "040"}],
    }


class LearningAIReviewTests(unittest.TestCase):
    def test_payload_is_sanitized_and_urls_have_no_query(self):
        payload = _safe_action({**_action(), "password": "never-send", "cookies": "never-send"})
        text = str(payload)
        self.assertNotIn("oauth_code", text)
        self.assertNotIn("token=hidden", text)
        self.assertNotIn("never-send", text)

    def test_recorded_values_are_not_in_learning_trace(self):
        trace = build_raw_learning_trace([{"event_type": "fill", "selector": "#grupo", "value": "real-client-value"}])
        self.assertNotIn("real-client-value", str(trace))

    def test_suggestions_cannot_change_captured_target(self):
        result = validate_ai_review_suggestions(
            _action(),
            {
                "suggested_extraction_targets": [
                    {"label": "same", "selector": "#resultado"},
                    {"label": "invented", "selector": "#other"},
                ],
                "variable_schema": [{"key": "grupo", "label": "Grupo"}, {"key": "invented", "label": "No"}],
            },
        )
        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["rejected_count"], 2)

    def test_learning_analysis_contract_is_valid(self):
        contract = learning_ai_analysis_contract({"ai_reviewed": True, "extraction_target": "parcelas"})
        self.assertTrue(isinstance(contract["selector_analysis"], list))
        self.assertTrue(contract["quality"]["ai_reviewed"])

    def test_timeout_uses_deterministic_fallback(self):
        with patch(
            "backend.services.ai_observer.openai_configuration_status",
            return_value={"enabled": True, "configured": True, "model": "gpt-5.4-mini", "provider": "openai_compatible"},
        ), patch("backend.services.ai_settings.effective_settings", return_value=SimpleNamespace(api_key="test-key")), patch(
            "backend.services.ai_observer.ChatOpenAI", side_effect=TimeoutError("timeout")
        ):
            result = asyncio.run(analyze_recorded_action_with_ai(_action()))
        self.assertFalse(result["ai_reviewed"])
        self.assertIn("replay_hints", result)

    def test_invalid_response_uses_fallback(self):
        fake = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="not json")))
        with patch(
            "backend.services.ai_observer.openai_configuration_status",
            return_value={"enabled": True, "configured": True, "model": "gpt-5.4-mini", "provider": "openai_compatible"},
        ), patch("backend.services.ai_settings.effective_settings", return_value=SimpleNamespace(api_key="test-key")), patch(
            "backend.services.ai_observer.ChatOpenAI", return_value=fake
        ):
            result = asyncio.run(analyze_recorded_action_with_ai(_action()))
        self.assertFalse(result["ai_reviewed"])
        self.assertIn("ação salva", result["ai_observer_summary"])

    def test_provider_http_failures_use_fallback_without_secret(self):
        for failure in (RuntimeError("401"), RuntimeError("429"), RuntimeError("500")):
            fake = SimpleNamespace(ainvoke=AsyncMock(side_effect=failure))
            with self.subTest(error=str(failure)), patch(
                "backend.services.ai_observer.openai_configuration_status",
                return_value={"enabled": True, "configured": True, "model": "gpt-5.4-mini", "provider": "openai_compatible"},
            ), patch("backend.services.ai_settings.effective_settings", return_value=SimpleNamespace(api_key="test-key")), patch(
                "backend.services.ai_observer.ChatOpenAI", return_value=fake
            ):
                result = asyncio.run(analyze_recorded_action_with_ai(_action()))
            self.assertFalse(result["ai_reviewed"])
            self.assertNotIn("test-key", str(result))

    def test_review_is_reused_and_invalidated_by_evidence_change(self):
        session = SimpleNamespace(
            id="fixture-session",
            guided_learning={"name": "Fixture", "run_start_strategy": "external_entry_each_run"},
            learning_events=[{"event_type": "fill", "selector": "#grupo"}],
            steps=[{"tipo": "preencher", "seletor": "#grupo", "variavel": "grupo"}],
            outputs=[],
            extraction_review={},
            external_system_id="system",
            access_profile_id="profile",
            learning_synthesis={},
            ai_review={},
        )
        manager = DemoSessionManager()
        action = _action()
        review = {"ai_reviewed": True, "ai_observer_summary": "ok", "suggested_extraction_targets": [], "variable_schema": []}

        async def run():
            with patch("backend.services.demo_session.persist_learning_session"), patch(
                "backend.services.ai_observer.openai_configuration_status",
                return_value={"enabled": True, "configured": True, "model": "gpt-5.4-mini"},
            ), patch("backend.services.ai_observer.analyze_recorded_action_with_ai", new=AsyncMock(return_value=review)) as call:
                await manager._review_learning_action(session, action)
                await manager._review_learning_action(session, action)
                session.steps.append({"tipo": "clicar", "seletor": "#consultar"})
                await manager._review_learning_action(session, action)
                return call.await_count

        self.assertEqual(asyncio.run(run()), 2)
        self.assertNotEqual(learning_evidence_fingerprint(session), "")


if __name__ == "__main__":
    unittest.main()
