"""Tenant-scoped external identities used to establish an execution context."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from backend.db import ClientList, ExternalAccessProfile, ExternalSystem, SessionLocal


class AccessProfileError(ValueError):
    pass


def current_external_system_id() -> str | None:
    with SessionLocal() as db:
        row = db.scalar(select(ExternalSystem).order_by(ExternalSystem.updated_at.desc()))
        return row.id if row else None


def _public(row: ExternalAccessProfile, *, system_name: str = "") -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "external_system_id": row.external_system_id,
        "external_system_name": system_name,
        "display_name": row.display_name,
        "login_identifier": row.login_identifier,
        "external_code": row.external_code or "",
        "active": bool(row.active),
        "session_status": "unknown",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_access_profiles(*, tenant_id: str = "default", external_system_id: str | None = None) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = select(ExternalAccessProfile, ExternalSystem.name).join(ExternalSystem, ExternalSystem.id == ExternalAccessProfile.external_system_id).where(ExternalAccessProfile.tenant_id == tenant_id)
        if external_system_id:
            query = query.where(ExternalAccessProfile.external_system_id == str(external_system_id))
        rows = db.execute(query.order_by(ExternalAccessProfile.display_name)).all()
        return [_public(row, system_name=name) for row, name in rows]


def get_access_profile(profile_id: str, *, tenant_id: str = "default", active_only: bool = True) -> ExternalAccessProfile:
    with SessionLocal() as db:
        query = select(ExternalAccessProfile).where(ExternalAccessProfile.id == str(profile_id), ExternalAccessProfile.tenant_id == tenant_id)
        if active_only:
            query = query.where(ExternalAccessProfile.active.is_(True))
        row = db.scalar(query)
        if row is None:
            raise AccessProfileError("Perfil de acesso não encontrado.")
        return row


def access_profile_public(profile_id: str, *, tenant_id: str = "default") -> dict[str, Any]:
    with SessionLocal() as db:
        row = db.scalar(select(ExternalAccessProfile).where(ExternalAccessProfile.id == str(profile_id), ExternalAccessProfile.tenant_id == tenant_id))
        if row is None:
            raise AccessProfileError("Perfil de acesso não encontrado.")
        system = db.get(ExternalSystem, row.external_system_id)
        return _public(row, system_name=system.name if system else "")


def create_access_profile(*, external_system_id: str, display_name: str, login_identifier: str, external_code: str = "", tenant_id: str = "default") -> dict[str, Any]:
    name = str(display_name or "").strip()
    identifier = str(login_identifier or "").strip()
    if not name or not identifier:
        raise AccessProfileError("Informe o nome e o identificador do perfil.")
    with SessionLocal.begin() as db:
        system = db.scalar(select(ExternalSystem).where(ExternalSystem.id == str(external_system_id)))
        if system is None:
            raise AccessProfileError("Sistema externo não encontrado.")
        duplicate = db.scalar(select(ExternalAccessProfile).where(ExternalAccessProfile.tenant_id == tenant_id, ExternalAccessProfile.external_system_id == system.id, ExternalAccessProfile.login_identifier == identifier))
        if duplicate:
            raise AccessProfileError("Já existe um perfil com este identificador neste sistema.")
        row = ExternalAccessProfile(id=str(uuid4()), tenant_id=tenant_id, external_system_id=system.id, display_name=name, login_identifier=identifier, external_code=str(external_code or "").strip() or None, active=True)
        db.add(row)
        db.flush()
        return _public(row, system_name=system.name)


def update_access_profile(profile_id: str, *, display_name: str | None = None, external_code: str | None = None, active: bool | None = None, tenant_id: str = "default") -> dict[str, Any]:
    with SessionLocal.begin() as db:
        row = db.scalar(select(ExternalAccessProfile).where(ExternalAccessProfile.id == str(profile_id), ExternalAccessProfile.tenant_id == tenant_id))
        if row is None:
            raise AccessProfileError("Perfil de acesso não encontrado.")
        if display_name is not None and not str(display_name).strip():
            raise AccessProfileError("Informe o nome do perfil.")
        if display_name is not None:
            row.display_name = str(display_name).strip()
        if external_code is not None:
            row.external_code = str(external_code).strip() or None
        if active is not None:
            if not active:
                used = db.scalar(select(ClientList.id).where(ClientList.access_profile_id == row.id).limit(1))
                if used:
                    raise AccessProfileError("O perfil está associado a uma lista; desative a lista ou altere o vínculo antes de desativá-lo.")
            row.active = bool(active)
        system = db.get(ExternalSystem, row.external_system_id)
        return _public(row, system_name=system.name if system else "")


def validate_profile_binding(*, profile_id: str | None, external_system_id: str | None, tenant_id: str = "default") -> ExternalAccessProfile | None:
    if not profile_id:
        return None
    with SessionLocal() as db:
        row = db.scalar(select(ExternalAccessProfile).where(ExternalAccessProfile.id == str(profile_id), ExternalAccessProfile.tenant_id == tenant_id, ExternalAccessProfile.active.is_(True)))
        if row is None:
            raise AccessProfileError("Perfil de acesso não encontrado ou inativo.")
        if external_system_id and row.external_system_id != str(external_system_id):
            raise AccessProfileError("O perfil de acesso não pertence ao sistema externo informado.")
        return row


def validate_list_action_profile(*, list_id: str, action_profile_id: str | None, tenant_id: str = "default") -> str | None:
    with SessionLocal() as db:
        row = db.scalar(select(ClientList).where(ClientList.id == str(list_id), ClientList.tenant_id == tenant_id, ClientList.active.is_(True)))
        if row is None:
            raise AccessProfileError("Lista de clientes não encontrada.")
        if action_profile_id and row.access_profile_id != str(action_profile_id):
            raise AccessProfileError("A Action e a Lista usam perfis de acesso diferentes.")
        return row.access_profile_id


def validate_access_bootstrap(definition: dict[str, Any], *, profile_id: str | None) -> dict[str, Any]:
    """Validate learned bootstrap metadata without accepting ordinal account selectors."""
    if not profile_id:
        return {"valid": False, "code": "required_access_profile_missing"}
    bootstrap = definition.get("access_bootstrap")
    if not isinstance(bootstrap, list) or not bootstrap:
        return {"valid": False, "code": "access_bootstrap_missing"}
    ordinal = any(":nth-child(" in str(item.get("selector") or "") or ":nth-of-type(" in str(item.get("selector") or "") for item in bootstrap if isinstance(item, dict))
    if ordinal:
        return {"valid": False, "code": "access_bootstrap_ordinal_selector"}
    return {"valid": True, "code": "ok"}
