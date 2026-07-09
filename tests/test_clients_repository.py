from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.schemas.actions import ActionDetail
from backend.services.clients_repository import (
    create_client,
    deactivate_client,
    import_clients_csv,
    list_clients,
    list_groups,
    update_client,
    validate_clients_for_action,
)


def action_with_variables() -> ActionDetail:
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


class ClientsRepositoryTests(unittest.TestCase):
    def test_create_update_and_deactivate_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            client = create_client(
                {
                    "name": "Cliente 1",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                },
                path,
            )
            updated = update_client(
                client["id"],
                {
                    "name": "Cliente 1 Atualizado",
                    "group": "Lista Principal",
                    "active": True,
                    "variables": {"grupo": "935", "grupo_2": "111", "grupo_3": "00"},
                },
                path,
            )
            deactivated = deactivate_client(client["id"], path)

            self.assertEqual(updated["name"], "Cliente 1 Atualizado")
            self.assertEqual(updated["variables"]["grupo_2"], "111")
            self.assertFalse(deactivated["active"])

    def test_import_csv_preserves_leading_zeroes_and_updates_by_name_group(self) -> None:
        csv_text = (
            "\ufeffname,group,active,grupo,grupo_2,grupo_3,cota,vers_o\n"
            "Cliente 1,Lista Principal,true,935,110,00,110,00\n"
            "Cliente 1,Lista Principal,true,935,111,01,111,01\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            first = import_clients_csv(csv_text.splitlines()[0] + "\n" + csv_text.splitlines()[1] + "\n", path)
            second = import_clients_csv(csv_text.splitlines()[0] + "\n" + csv_text.splitlines()[2] + "\n", path)
            clients = list_clients(path=path)

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["variables"]["grupo_3"], "01")
        self.assertEqual(clients[0]["variables"]["vers_o"], "01")

    def test_list_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            create_client({"name": "A", "group": "Lista A", "variables": {}}, path)
            create_client({"name": "B", "group": "Lista B", "variables": {}}, path)

            self.assertEqual(list_groups(path), ["Lista A", "Lista B"])

    def test_validate_clients_for_action_identifies_ready_incomplete_and_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            create_client(
                {
                    "name": "Pronto",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "grupo_2": "110", "grupo_3": "00"},
                },
                path,
            )
            create_client(
                {
                    "name": "Incompleto",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "grupo_2": "111"},
                },
                path,
            )
            create_client(
                {
                    "name": "Inativo",
                    "group": "Lista Principal",
                    "active": False,
                    "variables": {"grupo": "935", "grupo_2": "112", "grupo_3": "00"},
                },
                path,
            )

            validation = validate_clients_for_action(
                action_with_variables(),
                client_group="Lista Principal",
                path=path,
            )

        self.assertEqual([item["name"] for item in validation["ready"]], ["Pronto"])
        self.assertEqual([item["name"] for item in validation["incomplete"]], ["Incompleto"])
        self.assertEqual(validation["incomplete"][0]["missing_variables"], ["grupo_3"])
        self.assertEqual([item["name"] for item in validation["inactive"]], ["Inativo"])


if __name__ == "__main__":
    unittest.main()
