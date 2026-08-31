from __future__ import annotations

import tests  # noqa: F401

import tempfile
import unittest
from pathlib import Path

from backend.schemas.actions import ActionDetail
from backend.services.clients_repository import (
    client_template_csv,
    create_client,
    deactivate_client,
    get_client_display_fields,
    import_clients_csv,
    list_clients,
    list_groups,
    resolve_variables_for_action,
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


def percentage_action() -> ActionDetail:
    return ActionDetail(
        id="porcentagem-a-pagar",
        key="Porcentagem a pagar",
        name="Porcentagem a pagar",
        description="Consulta porcentagem a pagar.",
        variables=[
            {"key": "grupo", "label": "Grupo", "required": True},
            {"key": "cota", "label": "Cota", "required": True},
            {"key": "vers_o", "label": "Versao", "required": True},
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

    def test_new_client_uses_friendly_canonical_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            client = create_client(
                {
                    "name": "Cliente 1",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "cota": "110", "versao": "00"},
                },
                path,
            )

        self.assertEqual(client["variables"]["grupo"], "935")
        self.assertEqual(client["variables"]["cota"], "110")
        self.assertEqual(client["variables"]["versao"], "00")
        self.assertEqual(client["display_variables"], {"grupo": "935", "cota": "110", "versao": "00"})

    def test_legacy_client_display_uses_cota_and_versao(self) -> None:
        display = get_client_display_fields(
            {"variables": {"grupo": "935", "grupo_2": "110", "grupo_3": "00"}}
        )
        display_vers_o = get_client_display_fields(
            {"variables": {"grupo": "935", "cota": "111", "vers_o": "01"}}
        )

        self.assertEqual(display, {"grupo": "935", "cota": "110", "versao": "00"})
        self.assertEqual(display_vers_o, {"grupo": "935", "cota": "111", "versao": "01"})

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
        self.assertEqual(clients[0]["variables"]["cota"], "111")
        self.assertEqual(clients[0]["variables"]["versao"], "01")

    def test_import_new_friendly_csv_preserves_leading_zeroes(self) -> None:
        csv_text = (
            "\ufeffname,group,active,grupo,cota,versao,notes\n"
            "Cliente 1,Lista Principal,true,935,110,00,teste\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            import_clients_csv(csv_text, path)
            clients = list_clients(path=path)

        self.assertEqual(clients[0]["variables"]["cota"], "110")
        self.assertEqual(clients[0]["variables"]["versao"], "00")

    def test_list_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            create_client({"name": "A", "group": "Lista A", "variables": {}}, path)
            create_client({"name": "B", "group": "Lista B", "variables": {}}, path)

            self.assertEqual(list_groups(path), ["Lista A", "Lista B"])

    def test_search_clients_matches_accented_name_and_all_display_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            create_client(
                {
                    "name": "Árvore Azul",
                    "group": "Lista Principal",
                    "variables": {"grupo": "900", "cota": "136", "versao": "00"},
                },
                path,
            )
            create_client(
                {
                    "name": "Outro Cliente",
                    "group": "Lista Principal",
                    "variables": {"grupo": "900", "cota": "999", "versao": "01"},
                },
                path,
            )

            self.assertEqual([item["name"] for item in list_clients(search="arvore", path=path)], ["Árvore Azul"])
            self.assertEqual([item["name"] for item in list_clients(search="900 136", path=path)], ["Árvore Azul"])
            self.assertEqual([item["name"] for item in list_clients(search="136", path=path)], ["Árvore Azul"])
            self.assertEqual([item["name"] for item in list_clients(search="01", path=path)], ["Outro Cliente"])

    def test_validate_clients_for_action_identifies_ready_incomplete_and_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            ready_client = create_client(
                {
                    "name": "Pronto",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "cota": "110", "versao": "00"},
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
        self.assertEqual(validation["ready"][0]["variables"], {"grupo": "935", "grupo_2": "110", "grupo_3": "00"})
        self.assertEqual([item["name"] for item in validation["incomplete"]], ["Incompleto"])
        self.assertEqual(validation["incomplete"][0]["missing_variables"], ["grupo_3"])
        self.assertEqual([item["name"] for item in validation["inactive"]], ["Inativo"])

    def test_resolve_variables_for_numero_de_parcelas_from_friendly_fields(self) -> None:
        client = {"variables": {"grupo": "935", "cota": "110", "versao": "00"}}

        resolved = resolve_variables_for_action(client, action_with_variables().variables)

        self.assertEqual(resolved, {"grupo": "935", "grupo_2": "110", "grupo_3": "00"})

    def test_resolve_variables_for_porcentagem_from_friendly_fields(self) -> None:
        client = {"variables": {"grupo": "935", "cota": "110", "versao": "00"}}

        resolved = resolve_variables_for_action(client, percentage_action().variables)

        self.assertEqual(resolved, {"grupo": "935", "cota": "110", "vers_o": "00"})

    def test_missing_cota_is_incomplete_for_cota_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clients.json"
            create_client(
                {
                    "name": "Sem cota",
                    "group": "Lista Principal",
                    "variables": {"grupo": "935", "versao": "00"},
                },
                path,
            )
            validation = validate_clients_for_action(action_with_variables(), client_group="Lista Principal", path=path)

        self.assertEqual(validation["ready"], [])
        self.assertEqual(validation["incomplete"][0]["missing_variables"], ["grupo_2"])

    def test_template_csv_uses_friendly_headers(self) -> None:
        template = client_template_csv()

        self.assertIn("id,name,group,active,grupo,cota,versao,notes", template)
        self.assertNotIn("grupo_2", template)
        self.assertNotIn("vers_o", template)


if __name__ == "__main__":
    unittest.main()
