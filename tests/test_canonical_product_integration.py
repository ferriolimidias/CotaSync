from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from backend.db import (
    Action,
    ActionVersion,
    Batch,
    BatchItem,
    Client,
    ClientList,
    DataSource,
    DataSourceField,
    ExternalAccessProfile,
    ExternalSystem,
    GoogleSyncPending,
    LearningSession,
    Run,
    SessionLocal,
    SpreadsheetConnector,
)
from backend.services.action_runner import run_action_sync
from backend.services.actions_repository import find_action, resolve_compatible_actions, save_learned_action
from backend.services.batch_runner import create_batch
from backend.services.execution_preflight import preflight_action_execution
from backend.services.google_sync_queue import pending_count, send_pending_google
from backend.services.learning_session_store import load_learning_session, persist_learning_session
from backend.services.system_spreadsheets import apply_action_outputs_to_system_spreadsheet
from backend.worker import PersistentBatchWorker
from backend.schemas.runs import ActionRunRequest


@pytest.fixture
def canonical_product():
    suffix = uuid4().hex
    ids = {key: f"integration-{key}-{suffix}" for key in ("system", "profile", "list", "sheet", "field", "session")}
    action_id = f"integration-action-{suffix}"
    version_id = f"{action_id}-v1"
    client_ids = [f"integration-client-{suffix}-{index}" for index in range(1, 4)]
    output_field_ids = [f"{ids['field']}-{index}" for index in range(1, 4)]

    with SessionLocal.begin() as db:
        db.add(ExternalSystem(
            id=ids["system"],
            name=f"Integration System {suffix}",
            config={
                "entry_url": "https://integration.example.test/entry",
                "expected_system_host": "integration.example.test",
                "run_start_strategy": "external_entry_each_run",
            },
        ))
        db.flush()
        db.add(ExternalAccessProfile(
            id=ids["profile"], tenant_id="default", external_system_id=ids["system"],
            display_name="Integration Access", login_identifier="integration@example.test",
            active=True, validation_status="available",
        ))
        db.flush()
        db.add(ClientList(id=ids["list"], tenant_id="default", name="Integration List", access_profile_id=ids["profile"], active=True))
        db.add(DataSource(
            id=ids["sheet"], name="Integration Sheet", source_type="system_spreadsheet", status="active",
            schema_metadata={}, configuration={"default_list_id": ids["list"]},
        ))
        for index, role in enumerate(("grupo", "cota", "versao"), start=1):
            db.add(DataSourceField(
                id=output_field_ids[index - 1], data_source_id=ids["sheet"], display_name=f"Resultado {index}",
                source_column_reference=f"column:{index}", semantic_role=f"resultado_{index}", data_type="string", active=True,
            ))
        db.add(SpreadsheetConnector(
            id=f"integration-connector-{suffix}", spreadsheet_id=ids["sheet"], connector_type="google_sheets",
            configuration={"spreadsheet_id": "synthetic-google-sheet", "tab": "Clientes"}, status="pending",
        ))
        db.flush()
        for index, client_id in enumerate(client_ids, start=0):
            db.add(Client(
                id=client_id, system_spreadsheet_id=ids["sheet"], list_id=ids["list"], name=f"Client {index + 1}",
                client_group="Integration List", active=True, grupo=str(100 + index), cota=str(200 + index),
                versao="00", variables={"grupo": str(100 + index), "cota": str(200 + index), "versao": "00"},
            ))

    session = SimpleNamespace(
        id=ids["session"], tenant_id="default", status="stopped", recording=False,
        publication_status="not_attempted", external_system_id=ids["system"], access_profile_id=ids["profile"],
        external_system_name="Integration System", external_login_url="https://integration.example.test/entry",
        access_profile_name="Integration Access", access_profile_email_or_identifier="integration@example.test",
        expected_system_host="integration.example.test",
        guided_learning={
            "name": "Integration Action", "objective": "Update sheet", "expected_result": "Result",
            "required_access_profile_id": ids["profile"], "allowed_list_ids": [ids["list"]],
            "run_start_strategy": "external_entry_each_run",
        },
        learning_events=[
            {"event_type": "entry", "url_before": "https://integration.example.test/entry"},
            {"event_type": "click", "selector": "[data-profile='integration']"},
        ],
        steps=[
            {"step_id": "step-1", "tipo": "preencher", "variavel": "grupo", "seletor": "#grupo", "before_state_id": "main", "after_state_id": "main"},
            {"step_id": "step-2", "tipo": "preencher", "variavel": "cota", "seletor": "#cota", "before_state_id": "main", "after_state_id": "main"},
            {"step_id": "step-3", "tipo": "preencher", "variavel": "versao", "seletor": "#versao", "before_state_id": "main", "after_state_id": "main"},
        ],
        outputs=[
            {"output_id": "resultado_1", "label": "Resultado 1", "destination": {"type": "system_sheet_field", "system_spreadsheet_id": ids["sheet"], "field_id": output_field_ids[0]}},
            {"output_id": "resultado_2", "label": "Resultado 2", "destination": {"type": "system_sheet_field", "system_spreadsheet_id": ids["sheet"], "field_id": output_field_ids[1]}},
            {"output_id": "resultado_3", "label": "Resultado 3", "destination": {"type": "system_sheet_field", "system_spreadsheet_id": ids["sheet"], "field_id": output_field_ids[2]}},
        ],
        recorder_errors=[], result_selection={}, extraction_review={}, final_page_snapshot={}, ai_review={"status": "fallback", "prompt_version": "learning-review-v2"},
    )
    persist_learning_session(session)

    definition = {
        "nome_amigavel": f"Integration Action {suffix}", "descricao": "synthetic", "url_inicial": "https://integration.example.test/entry",
        "external_system_id": ids["system"], "required_access_profile_id": ids["profile"],
        "access_profile_name": "Integration Access", "access_profile_email_or_identifier": "integration@example.test",
        "microsoft_saved_account_identifier": "integration@example.test", "microsoft_saved_account_text": "Integration Access",
        "expected_system_host": "integration.example.test",
        "allowed_list_ids": [ids["list"]], "run_start_strategy": "external_entry_each_run",
        "access_bootstrap": [{"event_type": "click", "selector": "[data-profile='integration']"}],
        "execution_model": "learned_graph", "browser_mode": "desktop_browser", "modo_teste": True, "tipo_execucao": "local_fixture",
        "robust_steps": session.steps, "passos_playwright": session.steps,
        "learned_states": [{"state_id": "main", "signature": {"host": "integration.example.test", "path": "/entry"}}],
        "learned_transitions": [{"transition_id": "transition-1", "sequence_index": 0, "from_state_id": "main", "to_state_id": "main", "step_id": "step-1", "action_type": "preencher"}],
        "variables": ["grupo", "cota", "versao"], "variable_schema": [{"key": "grupo", "required": True}, {"key": "cota", "required": True}, {"key": "versao", "required": True}],
        "variaveis_necessarias": ["grupo", "cota", "versao"], "extraction_targets": ["resultado_1", "resultado_2", "resultado_3"],
        "output_schema": {"resultado_1": {"type": "string"}, "resultado_2": {"type": "string"}, "resultado_3": {"type": "string"}},
        "outputs": session.outputs,
    }
    saved_action = save_learned_action(action_id, definition)
    action_id = str(saved_action.id)
    version_id = f"{action_id}-v1"

    yield {**ids, "action": action_id, "version": version_id, "clients": client_ids, "fields": output_field_ids}

    with SessionLocal.begin() as db:
        for model, key in ((GoogleSyncPending, "spreadsheet_id"), (SpreadsheetConnector, "spreadsheet_id"), (DataSourceField, "data_source_id"), (Client, "system_spreadsheet_id"), (BatchItem, "batch_id"), (Run, "action_id"), (Batch, "action_id"), (ActionVersion, "action_id"), (Action, "id"), (LearningSession, "id"), (DataSource, "id"), (ClientList, "id"), (ExternalAccessProfile, "id"), (ExternalSystem, "id")):
            values = [ids["sheet"]] if key == "spreadsheet_id" else ([ids["system"]] if key == "external_system_id" else ([ids["list"]] if key == "list_id" else ([ids["session"]] if key == "id" and model is LearningSession else ([action_id] if key in {"action_id", "id"} else []))))
            if model is SpreadsheetConnector:
                db.execute(delete(model).where(model.spreadsheet_id == ids["sheet"]))
            elif model is DataSourceField:
                db.execute(delete(model).where(model.data_source_id == ids["sheet"]))
            elif model is Client:
                db.execute(delete(model).where(model.system_spreadsheet_id == ids["sheet"]))
            elif model is BatchItem:
                db.execute(delete(model).where(model.batch_id.in_(select(Batch.id).where(Batch.action_id == action_id))))
            elif model is Run:
                db.execute(delete(model).where(model.action_id == action_id))
            elif model is Batch:
                db.execute(delete(model).where(model.action_id == action_id))
            elif model is ActionVersion:
                db.execute(delete(model).where(model.action_id == action_id))
            elif model is Action:
                db.execute(delete(model).where(model.id == action_id))
            elif model is LearningSession:
                db.execute(delete(model).where(model.id == ids["session"]))
            elif model is DataSource:
                db.execute(delete(model).where(model.id == ids["sheet"]))
            elif model is ClientList:
                db.execute(delete(model).where(model.id == ids["list"]))
            elif model is ExternalAccessProfile:
                db.execute(delete(model).where(model.id == ids["profile"]))
            elif model is ExternalSystem:
                db.execute(delete(model).where(model.id == ids["system"]))


def test_canonical_learning_publication_and_individual_preflight(canonical_product):
    ids = canonical_product
    restored = load_learning_session(ids["session"], tenant_id="default")
    assert restored is not None
    assert restored.access_profile_id == ids["profile"]
    assert restored.external_system_id == ids["system"]
    assert restored.allowed_list_ids == [ids["list"]]
    assert restored.run_start_strategy == "external_entry_each_run"
    action = find_action(ids["action"])
    assert action is not None
    assert action.required_access_profile_id == ids["profile"]
    assert action.run_start_strategy == "external_entry_each_run"
    assert action.required_access_profile_name == "Integration Access"
    assert action.variables and [item.key for item in action.variables] == ["grupo", "cota", "versao"]
    assert len(action.outputs) == 3
    assert resolve_compatible_actions([action], list_id=ids["list"], access_profile_id=ids["profile"]) == [action]
    result = preflight_action_execution(action, client_id=ids["clients"][0], variables={"grupo": "100", "cota": "200", "versao": "00"})
    assert result["ok"] is True
    assert result["run_start_strategy"] == "external_entry_each_run"

    with SessionLocal.begin() as db:
        version = db.get(ActionVersion, ids["version"])
        version.definition = {**version.definition, "access_bootstrap": []}
    assert preflight_action_execution(action, client_id=ids["clients"][0], variables={"grupo": "100", "cota": "200", "versao": "00"})["ok"] is False
    with SessionLocal.begin() as db:
        version = db.get(ActionVersion, ids["version"])
        version.definition = {**version.definition, "access_bootstrap": [{"event_type": "click", "selector": "[data-profile='integration']"}]}


def test_canonical_individual_and_batch_outputs_are_isolated_and_google_is_separate(canonical_product):
    ids = canonical_product
    action = find_action(ids["action"])
    assert action is not None
    values = {ids["clients"][0]: "040", ids["clients"][1]: "038", ids["clients"][2]: "041"}

    def fixture(_action, variables):
        value = values[str(variables["client_id"])]
        return {"status": "success", "dados_extraidos": {"resultado_1": value, "resultado_2": value + "-2", "resultado_3": value + "-3"}, "passos_executados": 3}

    with patch("backend.services.action_runner._run_local_fixture", side_effect=fixture):
        individual = asyncio.run(run_action_sync(action, ActionRunRequest(variables={"client_id": ids["clients"][0], "grupo": "100", "cota": "200", "versao": "00"})))
        assert individual.status == "success", individual.error_message
        apply_action_outputs_to_system_spreadsheet(run_id=individual.id, action_id=action.id, client_id=ids["clients"][0], variables={"grupo": "100", "cota": "200", "versao": "00"}, result_payload=individual.result_payload or {}, outputs=action.outputs)
        assert preflight_action_execution(action, list_id=ids["list"], spreadsheet_id=ids["sheet"])["ok"] is True
        catalog_action = find_action(ids["action"])
        assert catalog_action is not None and catalog_action.id == action.id and catalog_action.required_access_profile_id == ids["profile"]
        batch = create_batch(action_id=ids["action"], list_id=ids["list"], spreadsheet_id=ids["sheet"], client_ids=ids["clients"], delay_between_rows_seconds=0, auto_start=False)
        worker = PersistentBatchWorker("integration-worker")
        item_ids = [f"{batch['batch_id']}-item-{index}" for index in range(3)]
        for item_id in item_ids:
            assert asyncio.run(worker.execute_item(batch["batch_id"], item_id)) is None

    with SessionLocal() as db:
        runs = list(db.scalars(select(Run).where(Run.action_id == ids["action"])).all())
        outputs = {run.client_id: (run.extracted_data or {}).get("resultado_1") for run in runs}
        assert {outputs[client_id] for client_id in ids["clients"]} == {"040", "038", "041"}
        assert all(isinstance(value, str) for value in outputs.values())
        assert len({run.id for run in runs}) == 4
        assert pending_count(spreadsheet_id=ids["sheet"]) == 9

    with patch("backend.services.system_spreadsheets.sync_google_pending", return_value={"updates": 9}) as sync:
        result = send_pending_google(spreadsheet_id=ids["sheet"])
    assert result["synced"] == 9
    assert sync.call_count == 1
    assert pending_count(spreadsheet_id=ids["sheet"]) == 0
