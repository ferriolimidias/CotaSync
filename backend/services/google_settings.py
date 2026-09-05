"""Secure Service Account settings for the Google Sheets connector."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from backend.db import GoogleSettings, SessionLocal
from backend.services.secret_storage import get_settings_fernet

REQUIRED_FIELDS = {"type", "project_id", "private_key_id", "private_key", "client_email", "client_id", "token_uri"}


def validate_service_account(value: str | bytes) -> dict[str, Any]:
    try:
        raw = json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("O arquivo não contém um JSON válido.") from exc
    if not isinstance(raw, dict) or raw.get("type") != "service_account":
        raise ValueError("O JSON precisa ser uma credencial do tipo service_account.")
    missing = sorted(field for field in REQUIRED_FIELDS if not str(raw.get(field) or "").strip())
    if missing:
        raise ValueError("Credencial incompleta. Campos ausentes: " + ", ".join(missing))
    if not str(raw["private_key"]).startswith("-----BEGIN PRIVATE KEY-----"):
        raise ValueError("A credencial não contém uma private key válida.")
    return {str(key): value for key, value in raw.items()}


def _row(tenant_id: str = "default") -> GoogleSettings | None:
    with SessionLocal() as db:
        return db.scalar(select(GoogleSettings).where(GoogleSettings.tenant_id == tenant_id))


def _decrypt(row: GoogleSettings | None) -> dict[str, Any] | None:
    if row is None or not row.credentials_encrypted:
        return None
    try:
        return json.loads(get_settings_fernet().decrypt(row.credentials_encrypted.encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError, RuntimeError):
        return None


def effective_credentials(tenant_id: str = "default") -> tuple[dict[str, Any] | None, str]:
    stored = _decrypt(_row(tenant_id))
    if stored:
        return stored, "stored"
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        try:
            return validate_service_account(raw), "environment"
        except ValueError:
            return None, "none"
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                return validate_service_account(handle.read()), "environment"
        except (OSError, ValueError):
            return None, "none"
    return None, "none"


def public_settings(tenant_id: str = "default") -> dict[str, Any]:
    credentials, source = effective_credentials(tenant_id)
    row = _row(tenant_id)
    return {
        "configured": bool(credentials),
        "client_email": credentials.get("client_email") if credentials else None,
        "project_id": credentials.get("project_id") if credentials else None,
        "configured_at": row.configured_at.isoformat() if row and row.configured_at else None,
        "connection_status": row.connection_status if row else ("configured" if credentials else "not_configured"),
        "source": source,
    }


def save_credentials(value: str | bytes, tenant_id: str = "default") -> dict[str, Any]:
    credentials = validate_service_account(value)
    encrypted = get_settings_fernet().encrypt(json.dumps(credentials, ensure_ascii=False).encode("utf-8")).decode("ascii")
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        row = db.scalar(select(GoogleSettings).where(GoogleSettings.tenant_id == tenant_id))
        if row is None:
            row = GoogleSettings(tenant_id=tenant_id)
            db.add(row)
        row.credentials_encrypted = encrypted
        row.configured_at = now
        row.connection_status = "configured"
    return public_settings(tenant_id)


def remove_credentials(tenant_id: str = "default") -> dict[str, Any]:
    with SessionLocal.begin() as db:
        row = db.scalar(select(GoogleSettings).where(GoogleSettings.tenant_id == tenant_id))
        if row is not None:
            row.credentials_encrypted = None
            row.connection_status = "not_configured"
    return public_settings(tenant_id)


def mark_connection(status: str, tenant_id: str = "default") -> None:
    with SessionLocal.begin() as db:
        row = db.scalar(select(GoogleSettings).where(GoogleSettings.tenant_id == tenant_id))
        if row is not None:
            row.connection_status = status
