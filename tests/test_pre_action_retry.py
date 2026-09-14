from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.db import AccessCycle, Batch, BatchItem, Client, ExternalAccessProfile, ExternalSystem, Run, SessionLocal, WorkerInstance
from backend.services.batch_runner import (
    BATCH_STATUS_INTERRUPTED,
    ITEM_STATUS_ERROR,
    ITEM_STATUS_INTERRUPTED,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_RUNNING,
    ITEM_STATUS_SUCCESS,
    LEGACY_RECONCILIATION_REASON,
    LegacyExecutionReconciliationDenied,
    PreActionRetryDenied,
    reconcile_legacy_execution,
    retry_pre_action_batch_item,
)


def _fixture(*, item_status: str = ITEM_STATUS_INTERRUPTED, action_started: bool = False, batch_status: str = BATCH_STATUS_INTERRUPTED):
    suffix = uuid4().hex
    system_id, profile_id, batch_id, item_id, run_id, cycle_id, client_id = [f"retry-{suffix}-{name}" for name in ("system", "profile", "batch", "item", "run", "cycle", "client")]
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        db.add(ExternalSystem(id=system_id, name=system_id, config={"entry_url": "https://entry.test"}))
        db.flush()
        db.add(ExternalAccessProfile(id=profile_id, tenant_id="default", external_system_id=system_id, display_name="Retry test", login_identifier=f"{profile_id}@test.invalid", active=True))
        db.add(Client(id=client_id, name="Retry client", client_group="retry", active=True, variables={"grupo": "955", "cota": "532"}))
        db.flush()
        db.add(Batch(id=batch_id, status=batch_status, total_items=2, heartbeat_at=now - timedelta(minutes=5), action_id=None))
        db.add(BatchItem(id=item_id, batch_id=batch_id, client_id=client_id, position=20, status=item_status, input_variables={"grupo": "955", "cota": "532", "versao": "01"}, error_data={"reason": "old_failure"}, finished_at=now - timedelta(minutes=1)))
        db.add(BatchItem(id=f"{item_id}-later", batch_id=batch_id, client_id=None, position=21, status=ITEM_STATUS_PENDING, input_variables={"grupo": "900", "cota": "222"}))
        db.add(Run(id=run_id, batch_id=batch_id, client_id=client_id, access_profile_id=profile_id, external_system_id=system_id, status="running", input_variables={"grupo": "955", "cota": "532", "versao": "01"}, diagnostics={"_record": {"action_started": action_started, "execution_stage": "main_graph" if action_started else "pre_action"}, "_result_payload": {}}))
        db.add(AccessCycle(id=cycle_id, external_system_id=system_id, access_profile_id=profile_id, entry_url="https://entry.test", status="failed", worker_id=None, heartbeat_at=now - timedelta(minutes=5), events=[]))
        db.flush()
        item = db.get(BatchItem, item_id)
        item.run_id = run_id
    return system_id, profile_id, batch_id, item_id, run_id, cycle_id, client_id


def _cleanup(ids):
    system_id, profile_id, batch_id, item_id, run_id, cycle_id, client_id = ids
    with SessionLocal.begin() as db:
        db.query(BatchItem).filter(BatchItem.batch_id == batch_id).delete(synchronize_session=False)
        for model, value in ((Run, run_id), (Batch, batch_id), (AccessCycle, cycle_id), (Client, client_id), (ExternalAccessProfile, profile_id), (ExternalSystem, system_id)):
            row = db.get(model, value)
            if row is not None:
                db.delete(row)


def test_pre_action_retry_requeues_only_one_item_and_terminalizes_old_records():
    ids = _fixture()
    try:
        result = retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        assert result["ready_for_claim"] is True
        with SessionLocal() as db:
            item, run, cycle, batch, later = (db.get(BatchItem, ids[3]), db.get(Run, ids[4]), db.get(AccessCycle, ids[5]), db.get(Batch, ids[2]), db.get(BatchItem, f"{ids[3]}-later"))
            assert item.status == ITEM_STATUS_PENDING and item.run_id is None and item.result_data == {}
            assert run.status == "cancelled" and run.error_data["code"] == "PRE_ACTION_RETRY"
            assert cycle.status == "superseded" and cycle.error_code == "PRE_ACTION_RETRY"
            assert batch.status == "queued" and batch.processed_items == 0 and batch.success_items == 0
            assert later.status == ITEM_STATUS_PENDING
    finally:
        _cleanup(ids)


def test_retry_requires_persisted_pre_action_marker():
    ids = _fixture(action_started=True)
    try:
        with pytest.raises(PreActionRetryDenied) as error:
            retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        assert error.value.code == "RETRY_DENIED"
    finally:
        _cleanup(ids)


def test_retry_rejects_success_and_active_owner():
    success = _fixture(item_status=ITEM_STATUS_SUCCESS)
    try:
        with pytest.raises(PreActionRetryDenied) as error:
            retry_pre_action_batch_item(success[2], success[3], requested_run_id=success[4], requested_access_cycle_id=success[5])
        assert error.value.code == "ITEM_ALREADY_SUCCESS"
    finally:
        _cleanup(success)
    active = _fixture(item_status=ITEM_STATUS_ERROR, batch_status="running")
    try:
        with SessionLocal.begin() as db:
            db.get(Batch, active[2]).worker_id = "retry-worker"
            db.add(WorkerInstance(id="retry-worker", instance_id="retry-worker", status="running", heartbeat_at=datetime.now(UTC)))
        with pytest.raises(PreActionRetryDenied) as error:
            retry_pre_action_batch_item(active[2], active[3], requested_run_id=active[4], requested_access_cycle_id=active[5])
        assert error.value.code == "EXECUTION_STILL_OWNED"
    finally:
        with SessionLocal.begin() as db:
            db.query(WorkerInstance).filter(WorkerInstance.id == "retry-worker").delete()
        _cleanup(active)


def test_retry_is_idempotent_and_does_not_create_new_run_or_cycle():
    ids = _fixture()
    try:
        first = retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        second = retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        assert first == second
        with SessionLocal() as db:
            assert db.query(Run).filter(Run.batch_id == ids[2]).count() == 1
            assert db.query(AccessCycle).filter(AccessCycle.id == ids[5]).count() == 1
            assert db.get(BatchItem, ids[3]).retry_count == 1
    finally:
        _cleanup(ids)


def test_retry_preserves_exact_input_variables_and_claimability():
    ids = _fixture()
    try:
        retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        with SessionLocal() as db:
            item = db.get(BatchItem, ids[3])
            assert item.input_variables == {"grupo": "955", "cota": "532", "versao": "01"}
        from backend.services.batch_runner import claim_next_batch, claim_next_item
        assert claim_next_batch("retry-worker") == ids[2]
        assert claim_next_item(ids[2]) == ids[3]
    finally:
        with SessionLocal.begin() as db:
            item = db.get(BatchItem, ids[3])
            if item is not None:
                item.status = ITEM_STATUS_PENDING
        _cleanup(ids)


def test_two_concurrent_retries_do_not_duplicate_work():
    ids = _fixture()
    try:
        def call():
            try:
                return retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
            except PreActionRetryDenied as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call(), range(2)))
        assert all(result == results[0] or result == "EXECUTION_STILL_OWNED" for result in results)
        with SessionLocal() as db:
            assert db.get(BatchItem, ids[3]).retry_count == 1
            assert db.query(Run).filter(Run.batch_id == ids[2]).count() == 1
    finally:
        _cleanup(ids)


def test_legacy_missing_marker_denies_automatic_retry_but_allows_explicit_reconciliation():
    ids = _fixture()
    try:
        with SessionLocal.begin() as db:
            db.get(Run, ids[4]).diagnostics = {"_record": {}, "_result_payload": {}}
        with pytest.raises(PreActionRetryDenied) as denied:
            retry_pre_action_batch_item(ids[2], ids[3], requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        assert denied.value.code == "RETRY_DENIED"

        result = reconcile_legacy_execution(
            ids[2], ids[3], operator_acknowledgement=True,
            operator_reason="Revisão operacional documentada da execução legada.",
            evidence_reference="legacy-preaction-audit", actor="operator", actor_role="operator",
            requested_run_id=ids[4], requested_access_cycle_id=ids[5],
        )
        assert result["operator_override"] is True
        assert result["automatic_pre_action_proof"] is False
        with SessionLocal() as db:
            item, run, cycle, batch = (db.get(BatchItem, ids[3]), db.get(Run, ids[4]), db.get(AccessCycle, ids[5]), db.get(Batch, ids[2]))
            assert item.status == ITEM_STATUS_PENDING and item.run_id is None
            assert run.status == "cancelled" and run.diagnostics["legacy_operator_reconciliation"]["operator_override"] is True
            assert run.diagnostics["legacy_operator_reconciliation"]["automatic_pre_action_proof"] is False
            assert cycle.status == "superseded" and cycle.error_code == LEGACY_RECONCILIATION_REASON
            assert batch.status == "queued" and batch.processed_items == 0 and batch.success_items == 0
    finally:
        _cleanup(ids)


def test_legacy_reconciliation_requires_acknowledgement_and_reason():
    ids = _fixture()
    try:
        with pytest.raises(LegacyExecutionReconciliationDenied) as ack_error:
            reconcile_legacy_execution(ids[2], ids[3], operator_acknowledgement=False, operator_reason="x", actor="operator", actor_role="operator")
        assert ack_error.value.code == "OPERATOR_ACK_REQUIRED"
        with pytest.raises(LegacyExecutionReconciliationDenied) as reason_error:
            reconcile_legacy_execution(ids[2], ids[3], operator_acknowledgement=True, operator_reason="", actor="operator", actor_role="operator")
        assert reason_error.value.code == "OPERATOR_REASON_REQUIRED"
    finally:
        _cleanup(ids)


def test_legacy_reconciliation_blocks_active_owner_and_action_evidence():
    active = _fixture(item_status=ITEM_STATUS_RUNNING, batch_status="running")
    try:
        with SessionLocal.begin() as db:
            batch = db.get(Batch, active[2])
            batch.worker_id = "legacy-worker"
            batch.heartbeat_at = datetime.now(UTC)
            db.add(WorkerInstance(id="legacy-worker", instance_id="legacy-worker", status="running", heartbeat_at=datetime.now(UTC)))
        with pytest.raises(LegacyExecutionReconciliationDenied) as owner_error:
            reconcile_legacy_execution(active[2], active[3], operator_acknowledgement=True, operator_reason="owner check", actor="operator", actor_role="operator", requested_run_id=active[4], requested_access_cycle_id=active[5])
        assert owner_error.value.code == "EXECUTION_STILL_OWNED"
    finally:
        with SessionLocal.begin() as db:
            db.query(WorkerInstance).filter(WorkerInstance.id == "legacy-worker").delete()
        _cleanup(active)

    evidence = _fixture()
    try:
        with SessionLocal.begin() as db:
            db.get(Run, evidence[4]).step_trace = [{"step_index": 0, "status": "started"}]
        with pytest.raises(LegacyExecutionReconciliationDenied) as evidence_error:
            reconcile_legacy_execution(evidence[2], evidence[3], operator_acknowledgement=True, operator_reason="evidence check", actor="operator", actor_role="operator", requested_run_id=evidence[4], requested_access_cycle_id=evidence[5])
        assert evidence_error.value.code == "ACTION_EXECUTION_EVIDENCE_PRESENT"
    finally:
        _cleanup(evidence)


def test_legacy_reconciliation_preserves_order_counters_and_does_not_create_execution():
    ids = _fixture()
    try:
        with SessionLocal.begin() as db:
            success = BatchItem(id=f"{ids[3]}-success", batch_id=ids[2], client_id=None, position=19, status=ITEM_STATUS_SUCCESS, result_data={"value": "ok"}, input_variables={})
            db.add(success)
            db.get(Run, ids[4]).diagnostics = {"_record": {}, "_result_payload": {}}
        reconcile_legacy_execution(ids[2], ids[3], operator_acknowledgement=True, operator_reason="ordering check", actor="admin", actor_role="admin", requested_run_id=ids[4], requested_access_cycle_id=ids[5])
        with SessionLocal() as db:
            assert db.get(BatchItem, f"{ids[3]}-success").status == ITEM_STATUS_SUCCESS
            assert db.get(Batch, ids[2]).success_items == 1
            assert db.query(Run).filter(Run.batch_id == ids[2]).count() == 1
            assert db.query(AccessCycle).filter(AccessCycle.id == ids[5]).count() == 1
        from backend.services.batch_runner import claim_next_batch, claim_next_item
        assert claim_next_batch("reconcile-worker") == ids[2]
        assert claim_next_item(ids[2]) == ids[3]
        assert claim_next_item(ids[2]) is None
    finally:
        with SessionLocal.begin() as db:
            db.query(BatchItem).filter(BatchItem.id == f"{ids[3]}-success").delete()
        _cleanup(ids)


def test_legacy_reconciliation_is_idempotent_and_concurrent():
    ids = _fixture()
    try:
        with SessionLocal.begin() as db:
            db.get(Run, ids[4]).diagnostics = {"_record": {}, "_result_payload": {}}

        def call():
            return reconcile_legacy_execution(ids[2], ids[3], operator_acknowledgement=True, operator_reason="concurrency check", actor="operator", actor_role="operator", requested_run_id=ids[4], requested_access_cycle_id=ids[5])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call(), range(2)))
        assert sum(1 for result in results if result["idempotent"]) == 1
        with SessionLocal() as db:
            assert db.get(BatchItem, ids[3]).retry_count == 1
            assert db.query(Run).filter(Run.batch_id == ids[2]).count() == 1
            assert db.query(AccessCycle).filter(AccessCycle.id == ids[5]).count() == 1
    finally:
        _cleanup(ids)
