"""Tenant-scoped external identities used to establish an execution context."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from backend.db import (
    AccessCycle,
    Action,
    ActionVersion,
    Batch,
    ClientList,
    ExternalAccessProfile,
    ExternalSystem,
    LearningSession,
    Run,
    SessionLocal,
)
from backend.services.browser_providers import remove_browser_identity_storage
from backend.services.session_guardian import classify_microsoft_auth_state, detect_microsoft_account_picker


class AccessProfileError(ValueError):
    pass


def delete_access_profile(profile_id: str, *, tenant_id: str = "default") -> dict[str, Any]:
    """Delete a profile and leave operational dependencies explicitly unassigned."""
    profile_id = str(profile_id or "").strip()
    if not profile_id:
        raise AccessProfileError("Perfil de acesso não encontrado.")
    references: dict[str, bool] = {}
    with SessionLocal.begin() as db:
        profile = db.scalar(
            select(ExternalAccessProfile).where(
                ExternalAccessProfile.id == profile_id,
                ExternalAccessProfile.tenant_id == tenant_id,
            )
        )
        if profile is None:
            raise AccessProfileError("Perfil de acesso não encontrado.")

        checks = (
            ("client_lists", ClientList, ClientList.access_profile_id == profile_id),
            ("actions", Action, Action.required_access_profile_id == profile_id),
            ("action_versions", ActionVersion, ActionVersion.required_access_profile_id == profile_id),
            ("runs", Run, Run.access_profile_id == profile_id),
            ("batches", Batch, Batch.access_profile_id == profile_id),
            ("learning_sessions", LearningSession, LearningSession.access_profile_id == profile_id),
            ("access_cycles", AccessCycle, AccessCycle.access_profile_id == profile_id),
        )
        for name, model, criterion in checks:
            references[name] = db.scalar(select(model.id).where(criterion).limit(1)) is not None
        referenced = any(references.values())
        # Preserve historical rows, but remove the identity from every
        # operational context before deleting the profile itself.
        for model, column in (
            (ClientList, ClientList.access_profile_id),
            (Action, Action.required_access_profile_id),
            (ActionVersion, ActionVersion.required_access_profile_id),
            (Run, Run.access_profile_id),
            (Batch, Batch.access_profile_id),
            (LearningSession, LearningSession.access_profile_id),
        ):
            db.execute(update(model).where(column == profile_id).values({column.key: None}))
        cycles = list(db.scalars(select(AccessCycle).where(AccessCycle.access_profile_id == profile_id)))
        for cycle in cycles:
            cycle.access_profile_id = None
            if cycle.status not in {"succeeded", "failed", "cancelled"}:
                cycle.status = "cancelled"
                cycle.stage = "access_profile_deleted"
                cycle.error_code = "ACCESS_PROFILE_DELETED"
                cycle.error_message = "O perfil de acesso foi excluído antes da conclusão do ciclo."
                cycle.finished_at = datetime.now(UTC)
        db.delete(profile)
        result = {"status": "deleted", "profile_id": profile_id, "referenced": references}
    # Storage is independent of the database transaction and is always scoped by hash.
    remove_browser_identity_storage(profile_id)
    return result


def assign_action_access_profile(action_id: str, profile_id: str, *, tenant_id: str = "default") -> dict[str, Any]:
    """Explicitly bind an existing published Action to an active profile."""
    action_id = str(action_id or "").strip()
    profile_id = str(profile_id or "").strip()
    if not action_id or not profile_id:
        raise AccessProfileError("Action e perfil de acesso são obrigatórios.")
    with SessionLocal.begin() as db:
        action = db.get(Action, action_id)
        version = db.get(ActionVersion, action.published_version_id) if action and action.published_version_id else None
        profile = db.scalar(select(ExternalAccessProfile).where(ExternalAccessProfile.id == profile_id, ExternalAccessProfile.tenant_id == tenant_id, ExternalAccessProfile.active.is_(True)))
        if action is None or version is None:
            raise AccessProfileError("Action publicada não encontrada.")
        if profile is None:
            raise AccessProfileError("Perfil de acesso não encontrado ou inativo.")
        definition = dict(version.definition or {})
        expected_system_id = str(definition.get("external_system_id") or "").strip()
        if expected_system_id and expected_system_id != profile.external_system_id:
            raise AccessProfileError("O perfil não pertence ao sistema externo da Action.")
        list_ids = [str(item) for item in (action.allowed_list_ids or []) if str(item).strip()]
        if list_ids:
            lists = list(db.scalars(select(ClientList).where(ClientList.id.in_(list_ids), ClientList.tenant_id == tenant_id, ClientList.active.is_(True))))
            if len(lists) != len(list_ids) or any(row.access_profile_id not in {None, profile_id} for row in lists):
                raise AccessProfileError("O perfil não é compatível com as listas da Action.")
        action.required_access_profile_id = profile_id
        version.required_access_profile_id = profile_id
        definition["required_access_profile_id"] = profile_id
        version.definition = definition
        return {"action_id": action.id, "action_version_id": version.id, "access_profile_id": profile_id}


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
        "validation_status": row.validation_status or "unverified",
        "last_validated_at": row.last_validated_at.isoformat() if row.last_validated_at else None,
        "last_validation_reason": row.last_validation_reason or "",
        "identity_evidence": [str(item)[:255] for item in (row.identity_evidence or []) if str(item).strip()][:10],
        # Kept for compatibility with the existing live-validation response.
        "session_status": row.validation_status or "unverified",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_access_profiles(*, tenant_id: str = "default", external_system_id: str | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = select(ExternalAccessProfile, ExternalSystem.name).join(ExternalSystem, ExternalSystem.id == ExternalAccessProfile.external_system_id).where(ExternalAccessProfile.tenant_id == tenant_id)
        if external_system_id:
            query = query.where(ExternalAccessProfile.external_system_id == str(external_system_id))
        if active_only:
            query = query.where(ExternalAccessProfile.active.is_(True))
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


def active_access_profile_public(profile_id: str, *, tenant_id: str = "default") -> dict[str, Any]:
    """Return the sole identity context accepted by operational access flows."""
    with SessionLocal() as db:
        row = db.scalar(
            select(ExternalAccessProfile).where(
                ExternalAccessProfile.id == str(profile_id),
                ExternalAccessProfile.tenant_id == tenant_id,
                ExternalAccessProfile.active.is_(True),
            )
        )
        if row is None:
            raise AccessProfileError("Perfil de acesso não encontrado ou inativo.")
        system = db.get(ExternalSystem, row.external_system_id)
        return _public(row, system_name=system.name if system else "")


def record_profile_validation(
    profile_id: str,
    *,
    status: str,
    reason: str = "",
    identity_evidence: list[str] | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    allowed = {"available", "verified", "reauth_required", "not_found", "unknown", "browser_offline"}
    normalized = str(status or "unknown").strip()
    if normalized not in allowed:
        normalized = "unknown"
    with SessionLocal.begin() as db:
        row = db.scalar(
            select(ExternalAccessProfile).where(
                ExternalAccessProfile.id == str(profile_id),
                ExternalAccessProfile.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise AccessProfileError("Perfil de acesso não encontrado.")
        row.validation_status = normalized
        row.last_validated_at = datetime.now(UTC)
        row.last_validation_reason = str(reason or "")[:255] or None
        if identity_evidence is not None and normalized == "verified":
            row.identity_evidence = [str(item).strip()[:255] for item in identity_evidence if str(item).strip()][:10]
        system = db.get(ExternalSystem, row.external_system_id)
        return _public(row, system_name=system.name if system else "")


def validate_profile_from_observation(profile: dict[str, Any], observation: Any, *, tenant_id: str = "default") -> dict[str, Any]:
    """Classify and persist one profile using an already captured browser snapshot."""
    if not observation.browser_available:
        status, reason = "browser_offline", "browser_unavailable"
        available = False
        diagnostic = {"account_picker": "unknown", "matched_identifiers": [], "auth_state": "unknown"}
    elif not observation.page_available:
        status, reason = "unknown", "page_unavailable"
        available = False
        diagnostic = {"account_picker": "unknown", "matched_identifiers": [], "auth_state": "unknown"}
    else:
        text_content = str(observation.body_text or "")
        picker = detect_microsoft_account_picker(text_content, [str(profile.get("login_identifier") or "")])
        auth_state = classify_microsoft_auth_state(text_content)
        available = bool(picker["profile_available"])
        if auth_state in {"password_required", "mfa_required"}:
            status, reason = "reauth_required", auth_state
        elif picker["state"] == "account_picker" and not available:
            status, reason = "not_found", "account_not_found"
        else:
            status, reason = ("available", "profile_available") if available else ("unknown", "profile_not_confirmed")
        diagnostic = {
            "account_picker": picker["state"],
            "matched_identifiers": picker["available_identifiers"],
            "auth_state": auth_state,
        }
    persisted = record_profile_validation(str(profile["id"]), status=status, reason=reason, tenant_id=tenant_id)
    return {"profile": persisted, "available": available, "diagnostic": diagnostic}


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
    if any(
        not isinstance(item, dict)
        or str(item.get("event_type") or "").strip().lower() not in {"click", "clicar"}
        or not str(item.get("selector") or "").strip()
        for item in bootstrap
    ):
        return {"valid": False, "code": "access_bootstrap_event_invalid"}
    return {"valid": True, "code": "ok"}
