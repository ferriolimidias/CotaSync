#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from typing import Any

from sqlalchemy import select

from backend.db import SessionLocal, User
from backend.services.auth import hash_password, validate_password_policy, verify_password


def _read_password(username: str) -> str:
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    if password.strip() != password or not password:
        raise ValueError("Password cannot be empty or have leading/trailing whitespace.")
    validate_password_policy(password)
    if password.casefold() == username.casefold():
        raise ValueError("Password cannot be equal to the username.")
    if not any(ch.islower() for ch in password):
        raise ValueError("Password must include at least one lowercase letter.")
    if not any(ch.isupper() for ch in password):
        raise ValueError("Password must include at least one uppercase letter.")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("Password must include at least one digit.")
    if not any(not ch.isalnum() for ch in password):
        raise ValueError("Password must include at least one symbol.")
    return password


def _reset_password(username: str, password: str) -> dict[str, Any]:
    new_hash = hash_password(password)
    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            raise LookupError(f"User not found: {username}")
        user.password_hash = new_hash
        session.flush()
        verified = verify_password(password, user.password_hash)
        return {
            "username": user.username,
            "role": user.role,
            "active": bool(user.active),
            "password_hash_verified": bool(verified),
        }


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    cookie_header: str | None = None,
    csrf_token: str | None = None,
) -> tuple[int, dict[str, Any], list[str]]:
    data = None
    headers: dict[str, str] = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cookie_header:
        headers["Cookie"] = cookie_header
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return response.status, payload, response.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
        return exc.code, payload, exc.headers.get_all("Set-Cookie") or []


def _cookie_header(set_cookie_headers: list[str]) -> tuple[str, str | None]:
    cookie = SimpleCookie()
    for header in set_cookie_headers:
        cookie.load(header)
    parts: list[str] = []
    csrf_token: str | None = None
    for key, morsel in cookie.items():
        parts.append(f"{key}={morsel.value}")
        if key == "cotasync_csrf":
            csrf_token = morsel.value
    return "; ".join(parts), csrf_token


def _validate_api(base_url: str, username: str, password: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    login_status, login_payload, set_cookie_headers = _request_json(
        f"{base}/api/v1/auth/login",
        method="POST",
        body={"username": username, "password": password},
    )
    cookie_header, csrf_token = _cookie_header(set_cookie_headers)
    me_status, me_payload, _ = _request_json(f"{base}/api/v1/auth/me", cookie_header=cookie_header)
    logout_status, logout_payload, _ = _request_json(
        f"{base}/api/v1/auth/logout",
        method="POST",
        cookie_header=cookie_header,
        csrf_token=csrf_token,
    )
    user = me_payload.get("user") if isinstance(me_payload, dict) else {}
    return {
        "login_status": login_status,
        "login_ok": login_status == 200 and login_payload.get("status") == "ok",
        "auth_me_status": me_status,
        "auth_me_ok": me_status == 200 and user.get("username") == username and user.get("role") == "admin",
        "logout_status": logout_status,
        "logout_ok": logout_status == 200 and logout_payload.get("status") == "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a CotaSync user password securely.")
    parser.add_argument("--username", required=True, help="Username to update.")
    parser.add_argument("--validate-api", action="store_true", help="Validate auth endpoints after update.")
    parser.add_argument("--local-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--public-base-url", default="")
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        print("Username is required.", file=sys.stderr)
        return 2

    try:
        password = _read_password(username)
        result = _reset_password(username, password)
        if not result["password_hash_verified"]:
            raise RuntimeError("Stored password hash verification failed.")
        print(f"Password updated successfully for user: {result['username']}")
        print(f"User role: {result['role']}")
        print(f"User active: {str(result['active']).lower()}")
        print("Password hash verified: true")
        if args.validate_api:
            local = _validate_api(args.local_base_url, username, password)
            print(
                "Local API validation: "
                f"login={local['login_ok']} auth_me={local['auth_me_ok']} logout={local['logout_ok']}"
            )
            if args.public_base_url:
                public = _validate_api(args.public_base_url, username, password)
                print(
                    "Public API validation: "
                    f"login={public['login_ok']} auth_me={public['auth_me_ok']} logout={public['logout_ok']}"
                )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        try:
            password = ""
        except UnboundLocalError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
