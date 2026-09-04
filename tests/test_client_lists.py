from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4

import tests  # noqa: F401
from backend.services.client_lists import create_client_list, rename_client_list
from backend.services.clients_repository import validate_clients_for_action
from backend.db import Client, SessionLocal


class ClientListTests(unittest.TestCase):
    def test_list_rename_preserves_client_and_action_scope(self) -> None:
        list_data = create_client_list(f"Priscila {uuid4()}")
        with SessionLocal.begin() as db:
            db.add(Client(id=f"list-client-{uuid4()}", name="Cliente", client_group=list_data["name"], list_id=list_data["id"], grupo="935", cota="112", versao="00", variables={"grupo": "935", "cota": "112", "versao": "00"}, active=True))
        action = SimpleNamespace(variables=[], allowed_list_ids=[list_data["id"]])
        rename_client_list(list_data["id"], "Clientes Priscila")
        result = validate_clients_for_action(action, list_id=list_data["id"])
        self.assertEqual(len(result["ready"]), 1)

    def test_unscoped_action_allows_any_list_and_unknown_scope_excludes_client(self) -> None:
        list_data = create_client_list(f"Lista {uuid4()}")
        with SessionLocal.begin() as db:
            db.add(Client(id=f"list-client-{uuid4()}", name="Cliente", client_group=list_data["name"], list_id=list_data["id"], grupo="935", cota="112", versao="00", variables={"grupo": "935", "cota": "112", "versao": "00"}, active=True))
        self.assertEqual(len(validate_clients_for_action(SimpleNamespace(variables=[], allowed_list_ids=[]), list_id=list_data["id"])["ready"]), 1)
        self.assertEqual(len(validate_clients_for_action(SimpleNamespace(variables=[], allowed_list_ids=["missing"]), list_id=list_data["id"])["ready"]), 0)


if __name__ == "__main__":
    unittest.main()
