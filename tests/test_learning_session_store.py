from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import delete

from backend.db import LearningSession, SessionLocal
from backend.services.learning_session_store import persist_learning_session, sanitize_learning_value, session_snapshot


class LearningSessionStoreTests(unittest.TestCase):
    def test_sensitive_values_are_redacted_before_snapshot(self) -> None:
        value = sanitize_learning_value({
            "event_type": "fill",
            "example_value": "secret",
            "field_metadata": {"type": "password"},
            "access_token": "token-value",
        })
        self.assertEqual(value["example_value"], "[REDACTED]")
        self.assertEqual(value["access_token"], "[REDACTED]")

    def test_session_snapshot_preserves_steps_variables_outputs_without_runtime_handles(self) -> None:
        session = SimpleNamespace(
            id="snapshot-test",
            tenant_id="default",
            status="autenticada",
            recording=False,
            publication_status="failed",
            external_system_id="system-a",
            access_profile_id="profile-a",
            external_system_name="System A",
            external_login_url="https://example.test/entry",
            access_profile_name="Profile A",
            access_profile_email_or_identifier="profile@example.test",
            expected_system_host="example.test",
            guided_learning={
                "name": "Example",
                "objective": "Consulta",
                "expected_result": "Resultado",
                "required_access_profile_id": "profile-a",
                "run_start_strategy": "external_entry_each_run",
            },
            learning_events=[{"event_type": "fill", "variable_key": "grupo", "example_value": "945"}],
            steps=[{"tipo": "preencher", "variavel": "grupo", "before_state_id": "form", "after_state_id": "form"}],
            outputs=[{"output_id": "output-1", "label": "Resultado"}],
            recorder_errors=[],
            result_selection={},
            extraction_review={},
            final_page_snapshot={},
            ai_review={"status": "completed", "evidence_hash": "hash", "result": {"ai_reviewed": True}},
        )
        snapshot = session_snapshot(session)
        self.assertEqual(snapshot["recorded_steps"][0]["variavel"], "grupo")
        self.assertEqual(snapshot["variable_bindings"], ["grupo"])
        self.assertEqual(snapshot["outputs"][0]["output_id"], "output-1")
        self.assertEqual(snapshot["diagnostics"]["ai_review"]["status"], "completed")
        self.assertNotIn("playwright", snapshot)

    def test_empty_optional_foreign_keys_are_persisted_as_null(self) -> None:
        session = SimpleNamespace(
            id="empty-fk-snapshot",
            tenant_id="default",
            status="aguardando_login",
            recording=False,
            publication_status="not_attempted",
            external_system_id="",
            access_profile_id="",
            external_system_name="",
            external_login_url="",
            access_profile_name="",
            access_profile_email_or_identifier="",
            expected_system_host="",
            guided_learning={},
            learning_events=[],
            steps=[],
            outputs=[],
            recorder_errors=[],
            result_selection={},
            extraction_review={},
            final_page_snapshot={},
        )
        snapshot = session_snapshot(session)
        self.assertIsNone(snapshot["external_system_id"])
        self.assertIsNone(snapshot["access_profile_id"])

    def test_write_through_increments_revision_and_keeps_failed_publication_retryable(self) -> None:
        session_id = f"store-test-{uuid4()}"
        session = SimpleNamespace(
            id=session_id,
            tenant_id="default",
            status="autenticada",
            recording=False,
            publication_status="not_attempted",
            external_system_id=None,
            access_profile_id=None,
            external_system_name="",
            external_login_url="",
            access_profile_name="",
            access_profile_email_or_identifier="",
            expected_system_host="",
            guided_learning={"name": "Retry", "objective": "", "expected_result": ""},
            learning_events=[],
            steps=[{"tipo": "clicar", "before_state_id": "a", "after_state_id": "b"}],
            outputs=[],
            recorder_errors=[],
            result_selection={},
            extraction_review={},
            final_page_snapshot={},
        )
        try:
            first = persist_learning_session(session)
            session.publication_status = "failed"
            second = persist_learning_session(session, publication={"status": "failed", "error_code": "LEARNED_GRAPH_INVALID"})
            with SessionLocal() as db:
                row = db.get(LearningSession, session_id)
                self.assertEqual(first, 1)
                self.assertEqual(second, 2)
                self.assertEqual(row.revision, 2)  # type: ignore[union-attr]
                self.assertEqual(row.publication_status, "failed")  # type: ignore[union-attr]
        finally:
            with SessionLocal.begin() as db:
                db.execute(delete(LearningSession).where(LearningSession.id == session_id))
