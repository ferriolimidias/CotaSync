from __future__ import annotations

import tests  # noqa: F401

import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.db import Batch as DbBatch, BatchItem, Run as DbRun, SessionLocal, WorkerInstance
from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.services.batch_runner import (
    BatchIdempotencyConflict,
    BatchRunnerError,
    batch_results_csv,
    cancel_batch,
    claim_next_batch,
    create_batch,
    load_batch,
    parse_csv_rows,
    recover_stale_batches,
    resume_batch,
    validate_batch_rows,
)
from backend.worker import BrowserAdvisoryLock, PersistentBatchWorker
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
        output_schema={"Número de parcelas": {"type": "string"}},
        extraction_targets=["Número de parcelas"],
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


def persist_fake_run(run: RunRecord) -> RunRecord:
    with SessionLocal.begin() as session:
        if session.get(DbRun, run.id) is None:
            session.add(
                DbRun(
                    id=run.id,
                    status=run.status,
                    run_origin="automated_test",
                    input_variables={},
                    diagnostics={"_record": run.model_dump(), "_result_payload": run.result_payload or {}},
                )
            )
    return run


class BatchRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        with SessionLocal.begin() as session:
            session.query(WorkerInstance).delete()
            session.query(BatchItem).delete()
            session.query(DbBatch).delete()
            session.query(DbRun).filter(DbRun.run_origin == "automated_test").delete()

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
        self.assertEqual(loaded["status"], "queued")
        self.assertEqual(loaded["rows"][0]["status"], "pending")
        self.assertEqual(loaded["rows"][0]["variables"]["grupo_3"], "00")

    def test_create_batch_allows_multiple_queued_batches_for_postgres_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            first = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                batches_dir=Path(tmp),
                auto_start=False,
            )
            second = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "111", "grupo_3": "00"}],
                batches_dir=Path(tmp),
                auto_start=False,
            )

        self.assertNotEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "queued")

    def test_worker_executes_rows_sequentially_and_waits_delay(self) -> None:
        events: list[str] = []

        async def run_action(_action: ActionDetail, request: ActionRunRequest) -> RunRecord:
            row_number = len([event for event in events if event.startswith("start")]) + 1
            events.append(f"start-{request.variables['grupo_2']}")
            events.append(f"finish-{request.variables['grupo_2']}")
            return persist_fake_run(fake_run(row_number))

        async def scenario() -> dict:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "backend.services.batch_runner.find_action", return_value=fake_action()
            ), patch("backend.worker.find_action", return_value=fake_action()), patch(
                "backend.worker.run_action_sync", side_effect=run_action
            ), patch(
                "backend.worker.asyncio.sleep", new_callable=AsyncMock
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
                claimed = claim_next_batch("worker-test")
                self.assertEqual(claimed, batch["batch_id"])
                await PersistentBatchWorker("worker-test").execute_batch(batch["batch_id"])
                loaded = load_batch(batch["batch_id"], Path(tmp))
                self.assertIsNotNone(loaded)
                self.assertEqual(sleep_mock.await_args.args[0], 3.0)
                return loaded

        loaded = asyncio.run(scenario())

        self.assertEqual(events, ["start-110", "finish-110", "start-111", "finish-111"])
        self.assertEqual(loaded["status"], "completed")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["success", "success"])

    def test_row_error_does_not_stop_batch_and_sets_partial_success(self) -> None:
        async def run_action(_action: ActionDetail, request: ActionRunRequest) -> RunRecord:
            if request.variables["grupo_2"] == "110":
                raise RuntimeError("falha simulada")
            return persist_fake_run(fake_run(2))

        async def scenario() -> dict:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "backend.services.batch_runner.find_action", return_value=fake_action()
            ), patch("backend.worker.find_action", return_value=fake_action()), patch(
                "backend.worker.run_action_sync", side_effect=run_action
            ), patch(
                "backend.worker.asyncio.sleep", new_callable=AsyncMock
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
                claimed = claim_next_batch("worker-test")
                self.assertEqual(claimed, batch["batch_id"])
                await PersistentBatchWorker("worker-test").execute_batch(batch["batch_id"])
                loaded = load_batch(batch["batch_id"], Path(tmp))
                self.assertIsNotNone(loaded)
                return loaded

        loaded = asyncio.run(scenario())

        self.assertEqual(loaded["status"], "completed_with_errors")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["error", "success"])

    def test_results_csv_contains_required_columns_and_extracted_payload(self) -> None:
        batch = {
            "batch_id": "batch-1",
            "action_id": "numero-de-parcelas-pagas",
            "result_columns": [
                {"key": "client_name", "label": "Nome"},
                {"key": "grupo", "label": "Grupo"},
                {"key": "cota", "label": "Cota"},
                {"key": "versao", "label": "Versão"},
                {"key": "Número de parcelas", "label": "Número de parcelas"},
                {"key": "status", "label": "Status"},
            ],
            "rows": [
                {
                    "id": "item-1",
                    "index": 1,
                    "client_name": "Cliente 1",
                    "client_fields": {"grupo": "935", "cota": "110", "versao": "00"},
                    "variables": {"grupo": "935", "grupo_3": "00"},
                    "status": "success",
                    "status_label": "Sucesso",
                    "run_id": "run-1",
                    "output_values": {"Número de parcelas": "032"},
                    "error_message": "",
                    "started_at": "inicio",
                    "finished_at": "fim",
                }
            ],
        }

        csv_text = batch_results_csv(batch)

        self.assertIn("Nome,Grupo,Cota,Versão,Número de parcelas,Status", csv_text)
        self.assertIn("Cliente 1,935,110,00,032,Sucesso", csv_text)

    def test_batch_output_label_is_dynamic_and_screen_label_is_not_exported(self) -> None:
        action = fake_action()
        action.output_schema = {"Valor da parcela": {"type": "string"}}
        action.extraction_targets = ["Valor da parcela"]
        rendered = batch_results_csv({
            "result_columns": [
                {"key": "client_name", "label": "Nome"},
                {"key": "Valor da parcela", "label": "Valor da parcela"},
                {"key": "status", "label": "Status"},
            ],
            "rows": [{
                "client_name": "Cliente 1",
                "output_values": {"Valor da parcela": "123,45"},
                "status": "success",
                "status_label": "Sucesso",
            }],
        })
        self.assertIn("Nome,Valor da parcela,Status", rendered)
        self.assertIn("Cliente 1,\"123,45\",Sucesso", rendered)
        self.assertNotIn("Qtd. Pcls. Pagas", rendered)

    def test_create_batch_from_client_group_saves_client_metadata(self) -> None:
        validation = {
            "ready": [
                {
                    "id": "client-1",
                    "name": "Cliente 1",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                }
            ],
            "incomplete": [],
            "inactive": [],
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "backend.services.batch_runner.find_action", return_value=fake_action()
        ), patch("backend.services.batch_runner.validate_clients_for_action", return_value=validation):
            batch = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[],
                client_group="Lista Principal",
                requested_by="test",
                batches_dir=Path(tmp),
                auto_start=False,
            )

        self.assertEqual(batch["source"], "clients")
        self.assertEqual(batch["rows"][0]["client_id"], "client-1")
        self.assertEqual(batch["rows"][0]["client_name"], "Cliente 1")
        self.assertEqual(batch["rows"][0]["client_group"], "Lista Principal")
        self.assertEqual(batch["rows"][0]["variables"]["grupo_3"], "00")

    def test_idempotency_key_returns_existing_batch_without_duplicate_items(self) -> None:
        with patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            first = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                auto_start=False,
                idempotency_key="same-click",
            )
            second = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                auto_start=False,
                idempotency_key="same-click",
            )

        self.assertEqual(first["batch_id"], second["batch_id"])
        with SessionLocal() as session:
            self.assertEqual(session.query(DbBatch).count(), 1)
            self.assertEqual(session.query(BatchItem).count(), 1)

    def test_idempotency_same_key_different_payload_conflicts(self) -> None:
        with patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                auto_start=False,
                idempotency_key="conflict-key",
                idempotency_user_id="operator",
            )
            with self.assertRaises(BatchIdempotencyConflict):
                create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[{"grupo": "935", "grupo_2": "999", "grupo_3": "00"}],
                    auto_start=False,
                    idempotency_key="conflict-key",
                    idempotency_user_id="operator",
                )

    def test_idempotency_same_key_different_user_does_not_collide(self) -> None:
        with patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            first = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                auto_start=False,
                idempotency_key="shared-key",
                idempotency_user_id="operator-a",
            )
            second = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                auto_start=False,
                idempotency_key="shared-key",
                idempotency_user_id="operator-b",
            )

        self.assertNotEqual(first["batch_id"], second["batch_id"])
        with SessionLocal() as session:
            self.assertEqual(session.query(DbBatch).count(), 2)

    def test_idempotency_race_same_user_same_payload_creates_one_batch(self) -> None:
        def submit() -> str:
            with patch("backend.services.batch_runner.find_action", return_value=fake_action()):
                batch = create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                    auto_start=False,
                    idempotency_key="race-key",
                    idempotency_user_id="operator",
                )
                return str(batch["batch_id"])

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: submit(), range(2)))

        self.assertEqual(results[0], results[1])
        with SessionLocal() as session:
            self.assertEqual(session.query(DbBatch).count(), 1)
            self.assertEqual(session.query(BatchItem).count(), 1)

    def test_two_workers_do_not_claim_same_batch(self) -> None:
        with patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            batch = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
                auto_start=False,
            )

        self.assertEqual(claim_next_batch("worker-a"), batch["batch_id"])
        self.assertIsNone(claim_next_batch("worker-b"))

    def test_browser_advisory_lock_blocks_second_executor(self) -> None:
        first = BrowserAdvisoryLock()
        second = BrowserAdvisoryLock()
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
        finally:
            first.release()
            second.release()

    def test_cancel_after_current_finishes_running_item_and_cancels_pending(self) -> None:
        batch_id_holder = [""]

        async def run_action(_action: ActionDetail, request: ActionRunRequest) -> RunRecord:
            if request.variables["grupo_2"] == "111":
                cancel_batch(batch_id_holder[0])
            return persist_fake_run(fake_run(int(request.variables["grupo_2"]) - 109))

        async def scenario() -> dict:
            with patch("backend.services.batch_runner.find_action", return_value=fake_action()), patch(
                "backend.worker.find_action", return_value=fake_action()
            ), patch("backend.worker.run_action_sync", side_effect=run_action), patch(
                "backend.worker.asyncio.sleep", new_callable=AsyncMock
            ):
                batch = create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[
                        {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                        {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                        {"grupo": "935", "grupo_2": "112", "grupo_3": "00"},
                    ],
                    auto_start=False,
                )
                batch_id_holder[0] = batch["batch_id"]
                self.assertEqual(claim_next_batch("worker-test"), batch["batch_id"])
                await PersistentBatchWorker("worker-test").execute_batch(batch["batch_id"])
                return load_batch(batch["batch_id"]) or {}

        loaded = asyncio.run(scenario())

        self.assertEqual(loaded["status"], "cancelled")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["success", "success", "cancelled"])

    def test_stale_running_item_interrupted_and_pending_resume(self) -> None:
        with patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            batch = create_batch(
                action_id="numero-de-parcelas-pagas",
                rows=[
                    {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                    {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                    {"grupo": "935", "grupo_2": "112", "grupo_3": "00"},
                ],
                auto_start=False,
            )
        with SessionLocal.begin() as session:
            db_batch = session.get(DbBatch, batch["batch_id"])
            self.assertIsNotNone(db_batch)
            from datetime import UTC, datetime, timedelta

            db_batch.status = "running"
            db_batch.worker_id = "dead-worker"
            db_batch.heartbeat_at = datetime.now(UTC) - timedelta(seconds=120)
            item1 = session.get(BatchItem, f"{batch['batch_id']}-item-0")
            item2 = session.get(BatchItem, f"{batch['batch_id']}-item-1")
            self.assertIsNotNone(item1)
            self.assertIsNotNone(item2)
            item1.status = "success"
            item2.status = "running"

        recovered = recover_stale_batches(60)
        loaded = load_batch(batch["batch_id"])

        self.assertEqual(recovered, 1)
        self.assertEqual(loaded["status"], "queued")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["success", "interrupted", "pending"])

    def test_external_session_expired_interrupts_batch_without_next_item(self) -> None:
        async def run_action(_action: ActionDetail, _request: ActionRunRequest) -> RunRecord:
            run = fake_run(1, status="error")
            run.result_payload = {"reason": "external_session_expired", "operator_action_required": True}
            run.error_message = "Sessao expirada"
            return persist_fake_run(run)

        async def scenario() -> dict:
            with patch("backend.services.batch_runner.find_action", return_value=fake_action()), patch(
                "backend.worker.find_action", return_value=fake_action()
            ), patch("backend.worker.run_action_sync", side_effect=run_action):
                batch = create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[
                        {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                        {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                    ],
                    auto_start=False,
                )
                claim_next_batch("worker-test")
                await PersistentBatchWorker("worker-test").execute_batch(batch["batch_id"])
                return load_batch(batch["batch_id"]) or {}

        loaded = asyncio.run(scenario())

        self.assertEqual(loaded["status"], "interrupted")
        self.assertEqual([row["status"] for row in loaded["rows"]], ["error", "pending"])

    def test_operator_attention_pauses_same_item_and_resume_requeues_it(self) -> None:
        async def run_action(_action: ActionDetail, _request: ActionRunRequest) -> RunRecord:
            run = fake_run(1, status="error")
            run.result_payload = {
                "reason": "unknown_microsoft_auth",
                "session_state": "unknown_microsoft_auth",
                "operator_action_required": True,
                "retryable": True,
            }
            run.error_message = "A sessao externa precisa de atencao."
            return persist_fake_run(run)

        async def scenario() -> tuple[dict, dict]:
            with patch("backend.services.batch_runner.find_action", return_value=fake_action()), patch(
                "backend.worker.find_action", return_value=fake_action()
            ), patch("backend.worker.run_action_sync", side_effect=run_action):
                batch = create_batch(
                    action_id="numero-de-parcelas-pagas",
                    rows=[
                        {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                        {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                    ],
                    auto_start=False,
                )
                claim_next_batch("worker-test")
                await PersistentBatchWorker("worker-test").execute_batch(batch["batch_id"])
                paused = load_batch(batch["batch_id"]) or {}
                resumed = resume_batch(batch["batch_id"]) or {}
                return paused, resumed

        paused, resumed = asyncio.run(scenario())

        self.assertEqual(paused["status"], "interrupted")
        self.assertEqual([row["status"] for row in paused["rows"]], ["needs_attention", "pending"])
        self.assertEqual(paused["rows"][0]["error_data"]["session_state"], "unknown_microsoft_auth")
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual([row["status"] for row in resumed["rows"]], ["pending", "pending"])


if __name__ == "__main__":
    unittest.main()
