from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, Request, Response, status

Role = Literal["admin", "operator"]

SESSION_COOKIE = os.getenv("COTASYNC_SESSION_COOKIE", "cotasync_session")
CSRF_COOKIE = os.getenv("COTASYNC_CSRF_COOKIE", "cotasync_csrf")
SESSION_TTL_SECONDS = int(os.getenv("COTASYNC_SESSION_TTL_SECONDS", "28800"))

logger = logging.getLogger("cotasync.auth")


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: Role


def _secret() -> bytes:
    raw = os.getenv("COTASYNC_SESSION_SECRET", "").strip()
    if raw:
        return raw.encode("utf-8")
    logger.warning("COTASYNC_SESSION_SECRET ausente; sessoes reiniciam com segredo efemero.")
    generated = getattr(_secret, "_generated", None)
    if not generated:
        generated = secrets.token_urlsafe(48)
        setattr(_secret, "_generated", generated)
    return str(generated).encode("utf-8")


def hash_password(password: str, *, salt: str | None = None, iterations: int = 260_000) -> str:
    if not password:
        raise ValueError("Senha vazia nao pode ser armazenada.")
    salt_bytes = base64.urlsafe_b64decode(salt.encode("ascii")) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt_bytes).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = str(stored_hash or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        candidate = hash_password(password, salt=salt, iterations=iterations)
    except Exception:
        return False
    return hmac.compare_digest(candidate, stored_hash)


def _configured_users() -> dict[str, tuple[Role, str]]:
    users: dict[str, tuple[Role, str]] = {}
    for role in ("admin", "operator"):
        prefix = f"COTASYNC_{role.upper()}"
        username = os.getenv(f"{prefix}_USERNAME", role).strip()
        password_hash = os.getenv(f"{prefix}_PASSWORD_HASH", "").strip()
        password = os.getenv(f"{prefix}_PASSWORD", "").strip()
        if not username:
            continue
        if not password_hash and password:
            password_hash = hash_password(password)
        if password_hash:
            users[username] = (role, password_hash)  # type: ignore[arg-type]
    return users


def authenticate(username: str, password: str) -> AuthUser | None:
    configured = _configured_users()
    role_and_hash = configured.get(str(username or "").strip())
    if not role_and_hash:
        return None
    role, stored_hash = role_and_hash
    if not verify_password(password, stored_hash):
        return None
    return AuthUser(username=str(username).strip(), role=role)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def create_session_token(user: AuthUser, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": user.username,
        "role": user.role,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=SESSION_TTL_SECONDS)).timestamp()),
        "nonce": secrets.token_urlsafe(16),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def parse_session_token(token: str, *, now: datetime | None = None) -> AuthUser | None:
    try:
        body, signature = str(token or "").split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(body))
        if int(payload.get("exp") or 0) < int((now or datetime.now(UTC)).timestamp()):
            return None
        username = str(payload.get("sub") or "").strip()
        role = str(payload.get("role") or "").strip()
        if role not in {"admin", "operator"} or not username:
            return None
        return AuthUser(username=username, role=role)  # type: ignore[arg-type]
    except Exception:
        return None


def cookie_secure() -> bool:
    return os.getenv("COTASYNC_COOKIE_SECURE", "true").strip().lower() not in {"0", "false", "no", "off"}


def set_auth_cookies(response: Response, user: AuthUser) -> str:
    csrf_token = secrets.token_urlsafe(32)
    common: dict[str, Any] = {
        "httponly": True,
        "secure": cookie_secure(),
        "samesite": "lax",
        "max_age": SESSION_TTL_SECONDS,
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, create_session_token(user), **common)
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=cookie_secure(),
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    return csrf_token


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def user_from_request(request: Request) -> AuthUser | None:
    user = getattr(request.state, "auth_user", None)
    if isinstance(user, AuthUser):
        return user
    token = request.cookies.get(SESSION_COOKIE)
    user = parse_session_token(token or "")
    if user is not None:
        request.state.auth_user = user
    return user


def require_user(request: Request) -> AuthUser:
    user = user_from_request(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def require_admin(request: Request) -> AuthUser:
    user = require_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission required.")
    return user


def validate_csrf(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("X-CSRF-Token", "")
    return bool(cookie and header and hmac.compare_digest(cookie, header))
