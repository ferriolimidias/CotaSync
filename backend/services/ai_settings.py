"""Persistent, backend-only settings for the learning AI provider."""
from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from backend.db import AISettings, SessionLocal
from backend.services.secret_storage import get_settings_fernet

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
SUPPORTED_PROVIDERS = {"openai", "openai_compatible"}


def _env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _fernet() -> Fernet:
    return get_settings_fernet()


@dataclass(frozen=True)
class EffectiveAISettings:
    enabled: bool
    provider: str
    model: str
    base_url: str
    api_key: str
    api_key_source: str


def _row() -> AISettings | None:
    with SessionLocal() as db:
        return db.scalar(select(AISettings).where(AISettings.id == 1))


def _decrypt(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, RuntimeError):
        return ""


def effective_settings() -> EffectiveAISettings:
    row = _row()
    stored_key = _decrypt(row.api_key_encrypted if row else None)
    env_key_name = "AI_API_KEY" if _env_value("AI_API_KEY") else "OPENAI_API_KEY" if _env_value("OPENAI_API_KEY") else ""
    api_key = stored_key or _env_value("AI_API_KEY", "OPENAI_API_KEY")
    return EffectiveAISettings(
        enabled=bool(row.enabled) if row else os.getenv("AI_ENABLED", "false").lower() in {"1", "true", "yes"},
        provider=(row.provider if row else _env_value("AI_PROVIDER") or "openai_compatible"),
        model=(row.model if row else _env_value("AI_MODEL", "OPENAI_MODEL") or DEFAULT_MODEL),
        base_url=(row.base_url if row and row.base_url else _env_value("AI_BASE_URL", "OPENAI_BASE_URL") or DEFAULT_BASE_URL),
        api_key=api_key,
        api_key_source="stored" if stored_key else env_key_name or "none",
    )


def public_settings() -> dict[str, object]:
    current = effective_settings()
    return {
        "enabled": current.enabled,
        "provider": current.provider,
        "model": current.model,
        "base_url": current.base_url,
        "api_key_configured": bool(current.api_key),
        "api_key_source": current.api_key_source,
    }


def save_settings(*, enabled: bool, provider: str, model: str, base_url: str, api_key: str | None) -> dict[str, object]:
    provider = provider.strip().lower()
    model = model.strip()
    base_url = base_url.strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("AI_PROVIDER_UNSUPPORTED")
    if not model:
        raise ValueError("AI_MODEL_REQUIRED")
    with SessionLocal.begin() as db:
        row = db.get(AISettings, 1)
        if row is None:
            row = AISettings(id=1, enabled=enabled, provider=provider, model=model, base_url=base_url)
            db.add(row)
        else:
            row.enabled, row.provider, row.model, row.base_url = enabled, provider, model, base_url
        if api_key is not None:
            if not api_key.strip():
                raise ValueError("AI_API_KEY_REQUIRED")
            row.api_key_encrypted = _fernet().encrypt(api_key.strip().encode("utf-8")).decode("ascii")
        db.flush()
    return public_settings()


def remove_key() -> dict[str, object]:
    with SessionLocal.begin() as db:
        row = db.get(AISettings, 1)
        if row is not None:
            row.api_key_encrypted = None
    return public_settings()
