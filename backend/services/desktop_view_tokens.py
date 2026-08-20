"""Tokens temporarios e exclusivos para a visualizacao humana do Desktop Browser."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from backend.db import DesktopViewToken as DbDesktopViewToken, SessionLocal


DEFAULT_TOKEN_TTL_SECONDS = 1800
TOKEN_PURPOSE = "desktop_browser_view"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TOKEN_PATH = _ROOT / "data" / "runtime" / "desktop_view_tokens.json"
_LOCK = threading.RLock()


@dataclass(frozen=True)
class DesktopViewToken:
    token: str
    expires_at: datetime
    ttl_seconds: int


def token_ttl_seconds() -> int:
    raw = os.getenv("COTASYNC_DESKTOP_VIEW_TOKEN_TTL_SECONDS", str(DEFAULT_TOKEN_TTL_SECONDS))
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_TOKEN_TTL_SECONDS


def token_store_path() -> Path:
    configured = os.getenv("COTASYNC_DESKTOP_VIEW_TOKEN_PATH", "").strip()
    return Path(configured) if configured else _DEFAULT_TOKEN_PATH


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "tokens": {}}


def _load_store(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(payload, dict) or not isinstance(payload.get("tokens"), dict):
        return _empty_store()
    return payload


def _write_store(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _parse_expiry(record: Any) -> datetime | None:
    if not isinstance(record, dict) or record.get("purpose") != TOKEN_PURPOSE:
        return None
    try:
        parsed = datetime.fromisoformat(str(record["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cleanup_expired_tokens(*, now: datetime | None = None) -> int:
    current = (now or _utc_now()).astimezone(timezone.utc)
    if os.getenv("COTASYNC_TEST_LEGACY_JSON") != "1":
        with SessionLocal.begin() as session:
            rows = session.query(DbDesktopViewToken).filter(DbDesktopViewToken.expires_at <= current).all()
            for row in rows:
                session.delete(row)
            return len(rows)
    path = token_store_path()
    with _LOCK:
        payload = _load_store(path)
        records = payload["tokens"]
        expired = [digest for digest, record in records.items() if (_parse_expiry(record) or current) <= current]
        for digest in expired:
            records.pop(digest, None)
        if expired:
            _write_store(path, payload)
        return len(expired)


def create_token(ttl_seconds: int | None = None, *, now: datetime | None = None) -> DesktopViewToken:
    ttl = ttl_seconds if ttl_seconds is not None else token_ttl_seconds()
    if ttl <= 0:
        raise ValueError("Token TTL must be positive.")
    current = (now or _utc_now()).astimezone(timezone.utc)
    expires_at = current + timedelta(seconds=ttl)
    token = secrets.token_urlsafe(32)
    digest = _token_digest(token)
    if os.getenv("COTASYNC_TEST_LEGACY_JSON") != "1":
        with SessionLocal.begin() as session:
            session.query(DbDesktopViewToken).filter(DbDesktopViewToken.expires_at <= current).delete()
            session.add(DbDesktopViewToken(digest=digest, purpose=TOKEN_PURPOSE, created_at=current, expires_at=expires_at))
        return DesktopViewToken(token=token, expires_at=expires_at, ttl_seconds=ttl)
    path = token_store_path()

    with _LOCK:
        payload = _load_store(path)
        records = payload["tokens"]
        for stored_digest, record in list(records.items()):
            if (_parse_expiry(record) or current) <= current:
                records.pop(stored_digest, None)
        records[digest] = {
            "purpose": TOKEN_PURPOSE,
            "created_at": current.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        _write_store(path, payload)
    return DesktopViewToken(token=token, expires_at=expires_at, ttl_seconds=ttl)


def validate_token(token: str | None, *, now: datetime | None = None) -> bool:
    candidate = str(token or "")
    if not _TOKEN_PATTERN.fullmatch(candidate):
        return False
    current = (now or _utc_now()).astimezone(timezone.utc)
    digest = _token_digest(candidate)
    if os.getenv("COTASYNC_TEST_LEGACY_JSON") != "1":
        with SessionLocal.begin() as session:
            row = session.get(DbDesktopViewToken, digest)
            if row is None:
                return False
            valid = row.purpose == TOKEN_PURPOSE and row.expires_at > current
            if not valid:
                session.delete(row)
            return valid
    path = token_store_path()
    with _LOCK:
        payload = _load_store(path)
        record = payload["tokens"].get(digest)
        expires_at = _parse_expiry(record)
        valid = expires_at is not None and expires_at > current
        if expires_at is not None and expires_at <= current:
            payload["tokens"].pop(digest, None)
            _write_store(path, payload)
        return bool(valid)


def mask_token(token: str | None) -> str:
    candidate = str(token or "")
    if not candidate:
        return "<empty>"
    if len(candidate) <= 8:
        return "***"
    return f"{candidate[:4]}...{candidate[-4:]}"
