from __future__ import annotations

import threading
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import tests  # noqa: F401

from backend.db import AccessCycle, Batch, BatchItem, ExternalSystem, Run, SessionLocal, WorkerInstance
from backend.services.worker_reconciliation import (
    StaleWorkerReconciliationDenied,
    reconcile_stale_worker_instance,
)


class StaleWorkerReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker_id = f"reconcile-worker-{uuid4()}"
        self.batch_id = f"reconcile-batch-{uuid4()}"
        self.item_id = f"reconcile-item-{uuid4()}"
        self.system_id = f"reconcile-system-{uuid4()}"
        self.now = datetime.now(UTC)
        with SessionLocal.begin() as db:
            db.add(WorkerInstance(
                id=self.worker_id,
                instance_id=self.worker_id,
                status="running",
                started_at=self.now - timedelta(minutes=10),
                heartbeat_at=self.now - timedelta(minutes=10),
                current_batch_id=self.batch_id,
                current_batch_item_id=self.item_id,
                metadata_json={"keep": "value"},
            ))
            db.add(Batch(id=self.batch_id, status="queued", total_items=2, processed_items=1, success_items=1, error_items=0))
            db.add(BatchItem(id=self.item_id, batch_id=self.batch_id, position=2, status="pending", input_variables={"grupo": "955", "cota": "532"}))

    def tearDown(self) -> None:
        with SessionLocal.begin() as db:
            db.query(AccessCycle).filter(AccessCycle.external_system_id == self.system_id).delete(synchronize_session=False)
            db.query(ExternalSystem).filter(ExternalSystem.id == self.system_id).delete(synchronize_session=False)
            db.query(Run).filter(Run.id.like("reconcile-run-%")).delete(synchronize_session=False)
            db.query(BatchItem).filter(BatchItem.id == self.item_id).delete(synchronize_session=False)
            db.query(Batch).filter(Batch.id == self.batch_id).delete(synchronize_session=False)
            db.query(WorkerInstance).filter(WorkerInstance.id == self.worker_id).delete(synchronize_session=False)

    def test_stale_worker_is_offlined_and_refs_cleared_only(self) -> None:
        result = reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, actor="admin", now=self.now)
        self.assertEqual(result["new_status"], "offline")
        with SessionLocal() as db:
            worker = db.get(WorkerInstance, self.worker_id)
            batch = db.get(Batch, self.batch_id)
            item = db.get(BatchItem, self.item_id)
            self.assertEqual(worker.status, "offline")
            self.assertIsNone(worker.current_batch_id)
            self.assertIsNone(worker.current_batch_item_id)
            self.assertEqual(batch.status, "queued")
            self.assertEqual((batch.processed_items, batch.success_items, batch.error_items), (1, 1, 0))
            self.assertEqual(item.status, "pending")
            self.assertEqual(item.input_variables, {"grupo": "955", "cota": "532"})
            self.assertEqual(worker.metadata_json["worker_reconciliation_audit"][-1]["operation"], "STALE_WORKER_RECONCILIATION")

    def test_process_absence_confirmation_is_required(self) -> None:
        with self.assertRaisesRegex(StaleWorkerReconciliationDenied, "ausência"):
            reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=False, now=self.now)

    def test_fresh_worker_is_denied(self) -> None:
        with SessionLocal.begin() as db:
            db.get(WorkerInstance, self.worker_id).heartbeat_at = self.now
        with self.assertRaisesRegex(StaleWorkerReconciliationDenied, "heartbeat fresco"):
            reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now)

    def test_active_batch_owner_is_denied(self) -> None:
        with SessionLocal.begin() as db:
            worker = db.get(WorkerInstance, self.worker_id)
            worker.heartbeat_at = self.now - timedelta(minutes=10)
            batch = db.get(Batch, self.batch_id)
            batch.worker_id = self.worker_id
            batch.status = "running"
        with self.assertRaisesRegex(StaleWorkerReconciliationDenied, "batch operacional"):
            reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now)

    def test_fresh_access_cycle_owner_is_denied(self) -> None:
        with SessionLocal.begin() as db:
            db.add(ExternalSystem(id=self.system_id, name=self.system_id, config={}))
            db.flush()
            db.add(AccessCycle(id=f"reconcile-cycle-{uuid4()}", external_system_id=self.system_id, worker_id=self.worker_id, status="running", stage="access_start", entry_url="https://example.invalid", heartbeat_at=self.now))
        with self.assertRaisesRegex(StaleWorkerReconciliationDenied, "AccessCycle"):
            reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now)

    def test_active_run_owner_is_denied(self) -> None:
        with SessionLocal.begin() as db:
            db.add(Run(id=f"reconcile-run-{uuid4()}", status="running", runner=self.worker_id, batch_id=self.batch_id))
        with self.assertRaisesRegex(StaleWorkerReconciliationDenied, "Run ativa"):
            reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now)

    def test_idempotent_after_first_reconciliation(self) -> None:
        first = reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now)
        second = reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now + timedelta(seconds=1))
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertFalse(second["current_refs_cleared"])

    def test_concurrent_reconciliation_has_one_effect(self) -> None:
        results: list[dict] = []
        errors: list[Exception] = []

        def invoke() -> None:
            try:
                results.append(reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now))
            except Exception as exc:  # pragma: no cover - diagnostic assertion below
                errors.append(exc)

        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sum(not result["idempotent"] for result in results), 1)

    def test_isolated_operation_does_not_call_recovery_or_claim(self) -> None:
        with patch("backend.services.batch_runner.recover_stale_batches") as recover_batches, patch("backend.services.access_cycles.recover_stale_access_cycles") as recover_cycles, patch("backend.services.batch_runner.claim_next_item") as claim:
            reconcile_stale_worker_instance(self.worker_id, process_absent_confirmed=True, now=self.now)
        recover_batches.assert_not_called()
        recover_cycles.assert_not_called()
        claim.assert_not_called()


if __name__ == "__main__":
    unittest.main()
