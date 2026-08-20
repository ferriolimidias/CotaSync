"""Tokens temporarios e exclusivos para a visualizacao humana do Desktop Browser."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from backend.db import DesktopViewToken as DbDesktopViewToken, SessionLocal


DEFAULT_TOKEN_TTL_SECONDS = 1800
TOKEN_PURPOSE = "desktop_browser_view"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cleanup_expired_tokens(*, now: datetime | None = None) -> int:
    current = (now or _utc_now()).astimezone(timezone.utc)
    with SessionLocal.begin() as session:
        rows = session.query(DbDesktopViewToken).filter(DbDesktopViewToken.expires_at <= current).all()
        for row in rows:
            session.delete(row)
        return len(rows)


def create_token(ttl_seconds: int | None = None, *, now: datetime | None = None) -> DesktopViewToken:
    ttl = ttl_seconds if ttl_seconds is not None else token_ttl_seconds()
    if ttl <= 0:
        raise ValueError("Token TTL must be positive.")
    current = (now or _utc_now()).astimezone(timezone.utc)
    expires_at = current + timedelta(seconds=ttl)
    token = secrets.token_urlsafe(32)
    digest = _token_digest(token)
    with SessionLocal.begin() as session:
        session.query(DbDesktopViewToken).filter(DbDesktopViewToken.expires_at <= current).delete()
        session.add(DbDesktopViewToken(digest=digest, purpose=TOKEN_PURPOSE, created_at=current, expires_at=expires_at))
    return DesktopViewToken(token=token, expires_at=expires_at, ttl_seconds=ttl)


def validate_token(token: str | None, *, now: datetime | None = None) -> bool:
    candidate = str(token or "")
    if not _TOKEN_PATTERN.fullmatch(candidate):
        return False
    current = (now or _utc_now()).astimezone(timezone.utc)
    digest = _token_digest(candidate)
    with SessionLocal.begin() as session:
        row = session.get(DbDesktopViewToken, digest)
        if row is None:
            return False
        valid = row.purpose == TOKEN_PURPOSE and row.expires_at > current
        if not valid:
            session.delete(row)
        return valid


def mask_token(token: str | None) -> str:
    candidate = str(token or "")
    if not candidate:
        return "<empty>"
    if len(candidate) <= 8:
        return "***"
    return f"{candidate[:4]}...{candidate[-4:]}"
