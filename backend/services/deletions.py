"""Transactional destructive operations with dependency guards."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from backend.db import Action, ActionVersion, Client, ClientList, DataSource, Run, SessionLocal, SpreadsheetConnector

logger = logging.getLogger("cotasync.deletions")


class DeletionError(ValueError):
    pass


def _tenant(sheet: DataSource, tenant_id: str) -> bool:
    return (sheet.configuration or {}).get("tenant_id", "default") == tenant_id


def _client_in_tenant(db, client: Client, tenant_id: str) -> bool:
    if client.system_spreadsheet_id:
        sheet = db.get(DataSource, client.system_spreadsheet_id)
        if sheet is not None:
            return _tenant(sheet, tenant_id)
    if client.list_id:
        client_list = db.get(ClientList, client.list_id)
        if client_list is not None:
            return client_list.tenant_id == tenant_id
    return tenant_id == "default"


def _identity(client: Client) -> str:
    return "|".join(str(value or "") for value in (client.grupo, client.cota, client.versao))


def _suppress(db, client: Client) -> None:
    if not client.system_spreadsheet_id:
        return
    sheet = db.get(DataSource, client.system_spreadsheet_id)
    if sheet is None:
        return
    config = dict(sheet.configuration or {})
    suppressed = list(config.get("suppressed_client_identities") or [])
    identity = _identity(client)
    if identity and identity not in suppressed:
        suppressed.append(identity)
    config["suppressed_client_identities"] = suppressed
    sheet.configuration = config


def delete_client(client_id: str, *, tenant_id: str = "default") -> dict[str, Any]:
    with SessionLocal.begin() as db:
        client = db.get(Client, client_id)
        if client is None:
            raise DeletionError("Cliente não encontrado.")
        if not _client_in_tenant(db, client, tenant_id):
            raise DeletionError("Cliente não encontrado.")
        snapshot = {"id": client.id, "name": client.name, "list_id": client.list_id}
        _suppress(db, client)
        db.delete(client)
        logger.info("client_deleted id=%s list_id=%s", snapshot["id"], snapshot["list_id"])
        return snapshot


def delete_clients(client_ids: list[str], *, tenant_id: str = "default") -> dict[str, Any]:
    wanted = list(dict.fromkeys(str(item).strip() for item in client_ids if str(item).strip()))
    if not wanted:
        raise DeletionError("Selecione ao menos um cliente.")
    with SessionLocal.begin() as db:
        clients = list(db.scalars(select(Client).where(Client.id.in_(wanted))))
        if len(clients) != len(wanted):
            raise DeletionError("Um ou mais clientes não foram encontrados.")
        for client in clients:
            if not _client_in_tenant(db, client, tenant_id):
                raise DeletionError("Cliente não encontrado.")
            _suppress(db, client)
        for client in clients:
            db.delete(client)
        logger.info("clients_bulk_deleted count=%s ids=%s", len(clients), ",".join(wanted))
        return {"deleted": len(clients), "client_ids": wanted}


def delete_client_list(list_id: str, *, tenant_id: str = "default", delete_clients_too: bool = False) -> dict[str, Any]:
    with SessionLocal.begin() as db:
        client_list = db.scalar(select(ClientList).where(ClientList.id == list_id, ClientList.tenant_id == tenant_id, ClientList.active.is_(True)))
        if client_list is None:
            raise DeletionError("Lista de clientes não encontrada.")
        clients = list(db.scalars(select(Client).where(Client.list_id == list_id)))
        sheets = list(db.scalars(select(DataSource).where(DataSource.source_type == "system_spreadsheet")))
        linked_sheets = [sheet for sheet in sheets if _tenant(sheet, tenant_id) and (sheet.configuration or {}).get("default_list_id") == list_id]
        actions = list(db.scalars(select(Action).where(Action.scope_mode == "selected")))
        linked_actions = [action for action in actions if list_id in set(action.allowed_list_ids or [])]
        if (clients or linked_sheets) and not delete_clients_too:
            raise DeletionError(f"Lista possui {len(clients)} clientes e {len(linked_sheets)} planilhas; confirme a exclusão dos clientes.")
        if linked_sheets:
            raise DeletionError("A lista ainda está vinculada a uma Planilha do Sistema; remova o vínculo antes de excluir.")
        for action in linked_actions:
            remaining = [item for item in action.allowed_list_ids if item != list_id]
            action.allowed_list_ids = remaining
            action.scope_mode = "selected"
        for client in clients:
            _suppress(db, client)
            db.delete(client)
        db.delete(client_list)
        logger.info("client_list_deleted id=%s clients=%s actions=%s", list_id, len(clients), len(linked_actions))
        return {"deleted": True, "clients_deleted": len(clients), "actions_updated": len(linked_actions)}


def delete_system_spreadsheet(sheet_id: str, *, tenant_id: str = "default", delete_clients_too: bool = False) -> dict[str, Any]:
    with SessionLocal.begin() as db:
        sheet = db.get(DataSource, sheet_id)
        if sheet is None or sheet.source_type != "system_spreadsheet" or not _tenant(sheet, tenant_id):
            raise DeletionError("Planilha do Sistema não encontrada.")
        clients = list(db.scalars(select(Client).where(Client.system_spreadsheet_id == sheet_id)))
        fields = {field.id for field in sheet.fields} if hasattr(sheet, "fields") else set()
        bindings: list[str] = []
        for version in db.scalars(select(ActionVersion)):
            for output in (version.definition or {}).get("outputs", []) if isinstance(version.definition, dict) else []:
                destination = output.get("destination") if isinstance(output, dict) else {}
                if isinstance(destination, dict) and destination.get("system_spreadsheet_id") == sheet_id:
                    bindings.append(version.id)
        if bindings:
            raise DeletionError(f"Planilha possui campos usados por {len(set(bindings))} versões de Action; desvincule os outputs antes de excluir.")
        if clients and not delete_clients_too:
            raise DeletionError(f"Planilha possui {len(clients)} clientes; confirme a exclusão dos clientes.")
        for client in clients:
            db.delete(client)
        connectors = list(db.scalars(select(SpreadsheetConnector).where(SpreadsheetConnector.spreadsheet_id == sheet_id)))
        for connector in connectors:
            db.delete(connector)
        db.delete(sheet)
        logger.info("system_spreadsheet_deleted id=%s clients=%s connectors=%s", sheet_id, len(clients), len(connectors))
        return {"deleted": True, "clients_deleted": len(clients), "connectors_deleted": len(connectors)}
