from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.services import batch_runner
from backend.services.batch_runner import (
    BatchRunnerError,
    batch_results_csv,
    create_batch,
    load_batch,
    parse_csv_rows,
    validate_batch_rows,
)
from frontend.api_client import parse_batch_csv_text, validate_batch_rows_for_action


def fake_action() -> ActionDetail:
    return ActionDetail(
        id="numero-de-parcelas-pagas",
        key="Numero de parcelas pagas",
        name="Numero de parcelas pagas",
        description="Consulta parcelas pagas.",
        variables=[
            {"key": "grupo", "label": "Grupo", "required": True},
            {"key": "grupo_2", "label": "Grupo 2", "required": True},
            {"key": "grupo_3", "label": "Grupo 3", "required": True},
        ],
        steps_count=1,
        has_url=True,
        browser_mode="desktop_browser",
    )


def fake_run(index: int, status: str = "success") -> RunRecord:
    return RunRecord(
        id=f"run-{index}",
        action_id="numero-de-parcelas-pagas",
        action_key="Numero de parcelas pagas",
        status=status,  # type: ignore[arg-type]
        mode="sync",
        run_type="action_run",
        requested_by="test",
        created_at=f"2026-01-01T00:00:0{index}+00:00",
        started_at=f"2026-01-01T00:00:0{index}+00:00",
        finished_at=f"2026-01-01T00:00:0{index}+00:00",
        variables={},
        operational_summary=f"resultado {index}",
        result_payload={"dados_extraidos": {"Qtd. Pcls. Pagas": f"03{index}"}},
        error_message="" if status == "success" else "falha",
    )


class BatchRunnerTests(unittest.TestCase):
    def test_parse_csv_preserves_leading_zeroes_and_ignores_blank_rows(self) -> None:
        rows = parse_csv_rows("\ufeffgrupo,grupo_2,grupo_3\n935,110,00\n\n935,111,01\n")

        self.assertEqual(rows[0]["grupo_3"], "00")
        self.assertEqual(rows[1]["grupo_3"], "01")
        self.assertEqual(len(rows), 2)

    def test_frontend_csv_parser_preserves_leading_zeroes(self) -> None:
        rows = parse_batch_csv_text("grupo,cota,vers_o\n935,110,00\n")

        self.assertEqual(rows, [{"grupo": "935", "cota": "110", "vers_o": "00"}])

    def test_validate_required_columns_reports_missing_column(self) -> None:
        with self.assertRaises(BatchRunnerError) as ctx:
            validate_batch_rows(fake_action(), [{"grupo": "935", "grupo_2": "110"}])

        self.assertIn("grupo_3", str(ctx.exception))

    def test_frontend_validation_reports_missing_column(self) -> None:
        errors = validate_batch_rows_for_action(
            {
                "variables": [
                    {"key": "grupo", "required": True},
                    {"key": "grupo_3", "required": True},
                ]
            },
            [{"grupo": "935"}],
        )

        self.assertTrue(any("grupo_3" in error for error in errors))

    def test_create_batch_persists_pending_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            batch = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                batches_dir=Path(tmp),
                auto_start=False,
            )
            loaded = load_batch(batch["batch_id"], Path(tmp))

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["rows"][0]["status"], "pending")
        self.assertEqual(loaded["rows"][0]["variables"]["grupo_3"], "00")

    def test_does_not_allow_two_running_or_pending_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                batches_dir=Path(tmp),
                auto_start=False,
            )
            with self.assertRaises(BatchRunnerError):
                create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[{"grupo": "935", "grupo_2": "111", "grupo_3": "00"}],
                    batches_dir=Path(tmp),
                    auto_start=False,
                )

    def test_worker_executes_rows_sequentially_and_waits_delay(self) -> None:
        events: list[str] = []

        async def run_action(_action: ActionDetail, request: ActionRunRequest) -> RunRecord:
            row_number = len([event for event in events if event.startswith("start")]) + 1
            events.append(f"start-{request.variables['grupo_2']}")
            events.append(f"finish-{request.variables['grupo_2']}")
            return fake_run(row_number)

        async def scenario() -> dict:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "backend.services.batch_runner.find_action", return_value=fake_action()
            ), patch("backend.services.batch_runner.run_action_sync", side_effect=run_action), patch(
                "backend.services.batch_runner.asyncio.sleep", new_callable=AsyncMock
            ) as sleep_mock:
                batch = create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[
                        {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                        {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                    ],
                    delay_between_rows_seconds=3,
                    batches_dir=Path(tmp),
                    auto_start=False,
                )
                await batch_runner._run_batch_worker(batch["batch_id"], batches_dir=Path(tmp))
                loaded = load_batch(batch["batch_id"], Path(tmp))
                self.assertIsNotNone(loaded)
                self.assertEqual(sleep_mock.await_args.args[0], 3.0)
                return loaded

        loaded = asyncio.run(scenario())

        self.assertEqual(events, ["start-110", "finish-110", "start-111", "finish-111"])
        self.assertEqual(loaded["status"], "success")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["success", "success"])

    def test_row_error_does_not_stop_batch_and_sets_partial_success(self) -> None:
        async def run_action(_action: ActionDetail, request: ActionRunRequest) -> RunRecord:
            if request.variables["grupo_2"] == "110":
                raise RuntimeError("falha simulada")
            return fake_run(2)

        async def scenario() -> dict:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "backend.services.batch_runner.find_action", return_value=fake_action()
            ), patch("backend.services.batch_runner.run_action_sync", side_effect=run_action), patch(
                "backend.services.batch_runner.asyncio.sleep", new_callable=AsyncMock
            ):
                batch = create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[
                        {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                        {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                    ],
                    batches_dir=Path(tmp),
                    auto_start=False,
                )
                await batch_runner._run_batch_worker(batch["batch_id"], batches_dir=Path(tmp))
                loaded = load_batch(batch["batch_id"], Path(tmp))
                self.assertIsNotNone(loaded)
                return loaded

        loaded = asyncio.run(scenario())

        self.assertEqual(loaded["status"], "partial_success")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["error", "success"])

    def test_results_csv_contains_required_columns_and_extracted_payload(self) -> None:
        batch = {
            "batch_id": "batch-1",
            "action_id": "numero-de-parcelas-pagas",
            "rows": [
                {
                    "index": 1,
                    "variables": {"grupo": "935", "grupo_3": "00"},
                    "status": "success",
                    "run_id": "run-1",
                    "operational_summary": "032",
                    "dados_extraidos": {"Qtd. Pcls. Pagas": "032"},
                    "error_message": "",
                    "started_at": "inicio",
                    "finished_at": "fim",
                }
            ],
        }

        csv_text = batch_results_csv(batch)

        self.assertIn("batch_id,row_index,action_id,status,run_id", csv_text)
        self.assertIn('""grupo_3"": ""00""', csv_text)
        self.assertIn("Qtd. Pcls. Pagas", csv_text)


if __name__ == "__main__":
    unittest.main()
