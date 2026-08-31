from __future__ import annotations

import tests  # noqa: F401

import unittest
from uuid import uuid4

from backend.db import Action, ActionStep, ActionVersion, Batch, BatchItem, ExtractionContract, Run, Schedule, SessionLocal
from backend.services.actions_repository import ActionDeletionError, delete_or_archive_action, load_actions_catalog, save_learned_action


class ActionDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        suffix = uuid4().hex
        self.action_id = f"deletion-test-{suffix}"
        self.version_id = f"{self.action_id}-v1"
        self.run_ids: list[str] = []
        self.schedule_ids: list[str] = []
        self.batch_ids: list[str] = []
        with SessionLocal.begin() as session:
            action = Action(
                id=self.action_id,
                key=self.action_id,
                name="Ação de teste de exclusão",
                description="",
                status="published",
            )
            session.add(action)
            session.add(
                ActionVersion(
                    id=self.version_id,
                    action_id=self.action_id,
                    version_number=1,
                    status="published",
                    definition={"nome_amigavel": "Ação de teste de exclusão", "url_inicial": "https://example.test"},
                    variables={},
                )
            )
            session.flush()
            action.published_version_id = self.version_id
            session.add(ActionStep(id=f"{self.version_id}-step-0", action_version_id=self.version_id, step_index=0, step_type="clicar", selector="#ok"))
            session.add(
                ExtractionContract(
                    id=f"{self.version_id}-contract-1",
                    action_version_id=self.version_id,
                    target_name="Resultado",
                    screen_label="Resultado",
                    selector_data={"primary": "#resultado"},
                    anchor_data={},
                    validation_data={},
                    example_value="040",
                )
            )

    def tearDown(self) -> None:
        with SessionLocal.begin() as session:
            for run_id in self.run_ids:
                session.query(Run).filter(Run.id == run_id).delete(synchronize_session=False)
            session.query(Run).filter(Run.action_id == self.action_id).delete(synchronize_session=False)
            for schedule_id in self.schedule_ids:
                session.query(Schedule).filter(Schedule.id == schedule_id).delete(synchronize_session=False)
            for batch_id in self.batch_ids:
                session.query(BatchItem).filter(BatchItem.batch_id == batch_id).delete(synchronize_session=False)
                session.query(Batch).filter(Batch.id == batch_id).delete(synchronize_session=False)
            session.query(ActionStep).filter(ActionStep.action_version_id == self.version_id).delete(synchronize_session=False)
            session.query(ExtractionContract).filter(ExtractionContract.action_version_id == self.version_id).delete(synchronize_session=False)
            session.query(ActionVersion).filter(ActionVersion.id == self.version_id).delete(synchronize_session=False)
            session.query(Action).filter(Action.id == self.action_id).delete(synchronize_session=False)

    def test_without_history_hard_deletes_definition(self) -> None:
        result = delete_or_archive_action(self.action_id)
        self.assertEqual(result["status"], "deleted")
        with SessionLocal() as session:
            self.assertIsNone(session.get(Action, self.action_id))
            self.assertIsNone(session.get(ActionVersion, self.version_id))
            self.assertEqual(session.query(ActionStep).filter(ActionStep.action_version_id == self.version_id).count(), 0)
            self.assertEqual(session.query(ExtractionContract).filter(ExtractionContract.action_version_id == self.version_id).count(), 0)

    def test_with_terminal_history_hard_deletes_definition_and_preserves_run(self) -> None:
        run_id = f"run-{uuid4().hex}"
        self.run_ids.append(run_id)
        with SessionLocal.begin() as session:
            session.add(Run(id=run_id, action_id=self.action_id, action_version_id=self.version_id, status="success"))
        result = delete_or_archive_action(self.action_id)
        self.assertEqual(result["status"], "deleted")
        with SessionLocal() as session:
            self.assertIsNone(session.get(Action, self.action_id))
            self.assertIsNotNone(session.get(Run, run_id))
            self.assertIsNone(session.get(ActionVersion, self.version_id))
            self.assertIsNone(session.get(Run, run_id).action_id)

    def test_queued_run_is_rejected_without_changes(self) -> None:
        run_id = f"run-{uuid4().hex}"
        self.run_ids.append(run_id)
        with SessionLocal.begin() as session:
            session.add(Run(id=run_id, action_id=self.action_id, action_version_id=self.version_id, status="pending"))
        with self.assertRaisesRegex(ActionDeletionError, "execucao em andamento"):
            delete_or_archive_action(self.action_id)
        with SessionLocal() as session:
            self.assertIsNotNone(session.get(Action, self.action_id))

    def test_active_schedule_is_rejected_without_changes(self) -> None:
        schedule_id = f"schedule-{uuid4().hex}"
        self.schedule_ids.append(schedule_id)
        with SessionLocal.begin() as session:
            session.add(Schedule(id=schedule_id, name="Teste", action_id=self.action_id, frequency="once", active=True))
        with self.assertRaisesRegex(ActionDeletionError, "agendamento ativo"):
            delete_or_archive_action(self.action_id)
        with SessionLocal() as session:
            self.assertIsNotNone(session.get(Action, self.action_id))

    def test_completed_batch_is_preserved_when_definition_is_deleted(self) -> None:
        batch_id = f"batch-{uuid4().hex}"
        self.batch_ids.append(batch_id)
        with SessionLocal.begin() as session:
            session.add(
                Batch(
                    id=batch_id,
                    action_id=self.action_id,
                    action_version_id=self.version_id,
                    status="completed",
                    total_items=1,
                    processed_items=1,
                    success_items=1,
                )
            )
        result = delete_or_archive_action(self.action_id)
        self.assertEqual(result["status"], "deleted")
        with SessionLocal() as session:
            batch = session.get(Batch, batch_id)
            self.assertIsNotNone(batch)
            self.assertIsNone(batch.action_id)
            self.assertIsNone(batch.action_version_id)

    def test_active_run_is_rejected_without_changes(self) -> None:
        with SessionLocal.begin() as session:
            session.add(Run(id=f"run-{uuid4().hex}", action_id=self.action_id, action_version_id=self.version_id, status="running"))
        with self.assertRaisesRegex(ActionDeletionError, "execucao em andamento"):
            delete_or_archive_action(self.action_id)
        with SessionLocal() as session:
            self.assertEqual(session.get(Action, self.action_id).status, "published")

    def test_archived_action_is_not_in_operational_catalog(self) -> None:
        with SessionLocal.begin() as session:
            session.get(Action, self.action_id).status = "archived"
        ids = {action.id for action in load_actions_catalog().actions}
        self.assertNotIn(self.action_id, ids)

    def test_legacy_archived_definition_can_be_deleted(self) -> None:
        with SessionLocal.begin() as session:
            session.get(Action, self.action_id).status = "archived"
        result = delete_or_archive_action(self.action_id)
        self.assertEqual(result["status"], "deleted")
        with SessionLocal() as session:
            self.assertIsNone(session.get(Action, self.action_id))

    def test_deleted_slug_can_be_published_again(self) -> None:
        delete_or_archive_action(self.action_id)
        saved = save_learned_action(
            self.action_id,
            {
                "nome_amigavel": self.action_id,
                "objective": "Recriar ação após exclusão",
                "robust_steps": [],
            },
        )
        self.assertEqual(saved.id, self.action_id)
        with SessionLocal() as session:
            self.assertEqual(session.get(Action, self.action_id).status, "published")

    def test_missing_action_returns_not_found(self) -> None:
        with self.assertRaisesRegex(ActionDeletionError, "Acao nao encontrada"):
            delete_or_archive_action(f"missing-{uuid4().hex}")


if __name__ == "__main__":
    unittest.main()
