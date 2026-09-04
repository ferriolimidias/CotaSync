from __future__ import annotations

import unittest
from uuid import uuid4

import tests  # noqa: F401
from backend.db import Client, ClientList, Run, SessionLocal
from backend.services.client_lists import create_client_list
from backend.services.deletions import delete_client, delete_clients, delete_client_list
from backend.services.system_spreadsheets import create_system_spreadsheet
from sqlalchemy import select


class DeletionTests(unittest.TestCase):
    def test_client_delete_preserves_run_and_suppresses_future_sync(self) -> None:
        sheet = create_system_spreadsheet(f"Delete {uuid4()}", ["Nome", "Grupo", "Cota", "Versão"])
        client_id = f"delete-client-{uuid4()}"
        run_id = f"delete-run-{uuid4()}"
        with SessionLocal.begin() as db:
            db.add(Client(id=client_id, name="Cliente", client_group="Lista Principal", system_spreadsheet_id=sheet["id"], list_id=sheet["default_list_id"], grupo="935", cota="112", versao="00", variables={"nome": "Cliente", "grupo": "935", "cota": "112", "versao": "00"}, active=True))
            db.add(Run(id=run_id, action_id=None, client_id=client_id, status="success", extracted_data={"resultado": "123"}, input_variables={}))
        delete_client(client_id)
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(Run, run_id))
            config = db.get(__import__("backend.db", fromlist=["DataSource"]).DataSource, sheet["id"]).configuration
            self.assertIn("935|112|00", config.get("suppressed_client_identities", []))

    def test_bulk_delete_and_list_dependency_guard(self) -> None:
        list_data = create_client_list(f"Delete list {uuid4()}")
        ids = [f"bulk-{uuid4()}", f"bulk-{uuid4()}"]
        with SessionLocal.begin() as db:
            for client_id in ids:
                db.add(Client(id=client_id, name="Cliente", client_group=list_data["name"], list_id=list_data["id"], grupo="935", cota=client_id[-4:], versao="00", variables={}, active=True))
        with self.assertRaises(Exception):
            delete_client_list(list_data["id"])
        result = delete_clients(ids)
        self.assertEqual(result["deleted"], 2)
        self.assertTrue(delete_client_list(list_data["id"], delete_clients_too=True)["deleted"])


if __name__ == "__main__":
    unittest.main()
