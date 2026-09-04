"""Stable operational client lists."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from backend.db import ClientList, SessionLocal


class ClientListError(ValueError):
    pass


def list_client_lists(*, tenant_id: str = "default") -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = list(db.scalars(select(ClientList).where(ClientList.tenant_id == tenant_id, ClientList.active.is_(True)).order_by(ClientList.name)))
        return [{"id": row.id, "name": row.name, "active": row.active, "tenant_id": row.tenant_id} for row in rows]


def create_client_list(name: str, *, tenant_id: str = "default") -> dict[str, Any]:
    clean = str(name or "").strip()
    if not clean:
        raise ClientListError("Informe o nome da lista.")
    with SessionLocal.begin() as db:
        existing = db.scalar(select(ClientList).where(ClientList.tenant_id == tenant_id, ClientList.name == clean, ClientList.active.is_(True)))
        if existing:
            return {"id": existing.id, "name": existing.name, "active": existing.active, "tenant_id": existing.tenant_id}
        row = ClientList(id=str(uuid4()), tenant_id=tenant_id, name=clean, active=True)
        db.add(row)
        db.flush()
        return {"id": row.id, "name": row.name, "active": row.active, "tenant_id": row.tenant_id}


def require_client_list(list_id: str, *, tenant_id: str = "default") -> ClientList:
    with SessionLocal() as db:
        row = db.scalar(select(ClientList).where(ClientList.id == str(list_id), ClientList.tenant_id == tenant_id, ClientList.active.is_(True)))
        if row is None:
            raise ClientListError("Lista de clientes não encontrada.")
        return row


def rename_client_list(list_id: str, name: str, *, tenant_id: str = "default") -> dict[str, Any]:
    clean = str(name or "").strip()
    if not clean:
        raise ClientListError("Informe o nome da lista.")
    with SessionLocal.begin() as db:
        row = db.scalar(select(ClientList).where(ClientList.id == str(list_id), ClientList.tenant_id == tenant_id, ClientList.active.is_(True)))
        if row is None:
            raise ClientListError("Lista de clientes não encontrada.")
        row.name = clean
        return {"id": row.id, "name": row.name, "active": row.active, "tenant_id": row.tenant_id}
