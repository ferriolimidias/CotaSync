from __future__ import annotations

import tests  # noqa: F401

import unittest

from sqlalchemy import inspect

from backend.db import Action, ActionStep, ActionVersion, SessionLocal, engine
from backend.services.result_selection import build_extraction_contract_from_confirmed_result
from scripts.migrate_json_to_postgres import migrate


class PostgresRound2Tests(unittest.TestCase):
    def test_operational_schema_tables_exist(self) -> None:
        tables = set(inspect(engine).get_table_names())
        self.assertTrue(
            {
                "users",
                "clients",
                "actions",
                "action_versions",
                "action_steps",
                "extraction_contracts",
                "runs",
                "batches",
                "batch_items",
                "schedules",
            }.issubset(tables)
        )

    def test_migration_dry_run_reports_current_sources(self) -> None:
        result = migrate(False)
        self.assertEqual(result["source"]["clients"], 4)
        self.assertEqual(result["source"]["actions"], 2)
        self.assertEqual(result["source"]["runs"], 31)
        self.assertEqual(result["source"]["batches"], 1)
        self.assertEqual(result["planned"]["action_steps"], 16)

    def test_actions_have_published_v1_with_steps(self) -> None:
        with SessionLocal() as session:
            actions = session.query(Action).filter(
                Action.id.in_(["quantidade-de-parcelas", "quantidade-de-parcelas-2"])
            ).all()
            self.assertEqual({action.id for action in actions}, {"quantidade-de-parcelas", "quantidade-de-parcelas-2"})
            for action in actions:
                version = session.get(ActionVersion, action.published_version_id)
                self.assertIsNotNone(version)
                self.assertEqual(version.version_number, 1)
                steps = session.query(ActionStep).filter(ActionStep.action_version_id == version.id).all()
                self.assertGreater(len(steps), 0)

    def test_postgres_preserves_operational_strings(self) -> None:
        contract = build_extraction_contract_from_confirmed_result(
            target_name="Quantidade de parcelas",
            screen_label="Qtd. Pcls. Pagas",
            value="032",
            return_format="somente o valor",
        )
        self.assertEqual(contract["example_value"], "032")


if __name__ == "__main__":
    unittest.main()
