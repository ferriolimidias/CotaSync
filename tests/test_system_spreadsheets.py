from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import tests  # noqa: F401
from openpyxl import Workbook, load_workbook

from backend.services.system_spreadsheets import (
    create_system_spreadsheet,
    export_excel,
    import_excel,
    import_google,
    reconcile_schema,
    sync_google,
)


class SystemSpreadsheetTests(unittest.TestCase):
    def test_manual_sheet_has_stable_system_field_ids(self) -> None:
        sheet = create_system_spreadsheet("Teste interno", ["Nome", "Grupo", "Cota", "Versão"])
        self.assertEqual(len(sheet["fields"]), 4)
        self.assertEqual(len({field["field_id"] for field in sheet["fields"]}), 4)
        self.assertTrue(all(field["field_id"].startswith("field-") for field in sheet["fields"]))

    def test_schema_reconcile_preserves_ids_when_columns_are_reordered_or_renamed(self) -> None:
        sheet = create_system_spreadsheet("Schema estável", ["Nome", "Grupo", "Cota", "Versão"])
        ids = {field["internal_key"]: field["field_id"] for field in sheet["fields"]}
        renamed = reconcile_schema(sheet["id"], ["Nome", "Grupo", "Cota", "Parcelas pagas"])
        self.assertEqual(renamed["fields"][3]["field_id"], ids["versao"])
        reordered = reconcile_schema(sheet["id"], ["Cota", "Nome", "Parcelas pagas", "Grupo"])
        self.assertEqual({field["display_name"]: field["field_id"] for field in reordered["fields"]}["Cota"], ids["cota"])

    def test_excel_import_header_outside_first_row_skips_organizational_rows_and_preserves_zero(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Clientes"
        sheet.append(["Equipe Sul"])
        sheet.append(["Nome", "Grupo", "Cota", "Versão", "Resultado"])
        sheet.append(["Cliente 1", "935", "112", "00", "034"])
        output = io.BytesIO()
        workbook.save(output)
        imported = import_excel(name="Excel sintético", content=output.getvalue(), filename="clientes.xlsx", header_row=2)
        self.assertEqual(imported["client_count"], 1)
        self.assertEqual(imported["connectors"][0]["type"], "excel")
        self.assertEqual(imported["fields"][3]["display_name"], "Versão")
        exported = load_workbook(io.BytesIO(export_excel(imported["id"])), read_only=True)
        self.assertEqual(exported.active.cell(2, 4).value, "00")

    @patch("backend.services.system_spreadsheets._google_request")
    def test_google_import_and_both_connector_sync_use_one_system_sheet(self, request) -> None:
        request.return_value = {"values": [["Nome", "Grupo", "Cota", "Versão", "Resultado"], ["Cliente 1", "935", "112", "00", ""]]}
        sheet = import_google(name="Google sintético", url_or_id="sheet-id", tab="Clientes")
        self.assertEqual(sheet["client_count"], 1)
        self.assertEqual(len(sheet["connectors"]), 1)
        from backend.services.system_spreadsheets import _upsert_connector
        from backend.db import SessionLocal, DataSource
        from sqlalchemy import select
        with SessionLocal.begin() as db:
            canonical = db.scalar(select(DataSource).where(DataSource.id == sheet["id"]))
            _upsert_connector(db, canonical.id, "excel", {"filename": "export.xlsx"})
        updated = sync_google(sheet["id"], direction="inbound")
        self.assertEqual(updated["id"], sheet["id"])
        self.assertEqual({item["type"] for item in updated["connectors"]}, {"google_sheets", "excel"})

    @patch("backend.services.system_spreadsheets._google_request")
    def test_google_outbound_failure_does_not_remove_internal_sheet(self, request) -> None:
        request.return_value = {"values": [["Nome", "Grupo", "Cota", "Versão"], ["Cliente 2", "935", "113", "00"]]}
        sheet = import_google(name="Google falha", url_or_id="sheet-id-2", tab="Clientes")
        request.side_effect = RuntimeError("offline")
        with self.assertRaises(Exception):
            sync_google(sheet["id"], direction="outbound")
        self.assertEqual(sync_google.__name__, "sync_google")


if __name__ == "__main__":
    unittest.main()
