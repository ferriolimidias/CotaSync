from __future__ import annotations

import tests  # noqa: F401

from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.main import app
from backend.db import SessionLocal, User
from backend.services.auth import (
    MIN_PASSWORD_LENGTH,
    AuthUser,
    create_session_token,
    hash_password,
    reset_user_password,
)
from scripts.reset_user_password import _read_password
from tests.auth_helpers import TEST_AUTH_ENV, authenticated_client


class AuthSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        with SessionLocal.begin() as session:
            for username, password, role in (
                ("admin", "admin-password", "admin"),
                ("operator", "operator-password", "operator"),
            ):
                user = session.scalar(select(User).where(User.username == username))
                if user is None:
                    session.add(
                        User(
                            id=f"test-{username}",
                            username=username,
                            password_hash=hash_password(password),
                            role=role,
                            active=True,
                            auth_version=1,
                        )
                    )
                else:
                    user.password_hash = hash_password(password)
                    user.role = role
                    user.active = True
                    user.auth_version = 1

    def test_admin_login_me_and_logout(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password"})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(login.json()["user"]["role"], "admin")
            self.assertIn("httponly", login.headers.get("set-cookie", "").lower())

            me = client.get("/api/v1/auth/me")
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json()["user"]["username"], "admin")

            csrf = login.json()["csrf_token"]
            logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            self.assertEqual(logout.status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_password_policy_rejects_six_and_accepts_seven_or_more(self) -> None:
        self.assertEqual(MIN_PASSWORD_LENGTH, 7)
        with self.assertRaisesRegex(ValueError, "7"):
            hash_password("Abc1!")
        for password in ("Abc1!xy", "Abc1!xyz"):
            stored_hash = hash_password(password)
            self.assertTrue(stored_hash.startswith("pbkdf2_sha256$"))

    def test_reset_password_accepts_seven_characters_and_login_still_works(self) -> None:
        password = "Abc1!xy"
        reset_user_password("operator", password)
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            response = client.post("/api/v1/auth/login", json={"username": "operator", "password": password})
        self.assertEqual(response.status_code, 200)

    def test_reset_script_accepts_seven_characters(self) -> None:
        with patch("scripts.reset_user_password.getpass.getpass", side_effect=["Abc1!xy", "Abc1!xy"]):
            self.assertEqual(_read_password("operator"), "Abc1!xy")

    def test_reset_script_rejects_six_characters(self) -> None:
        with patch("scripts.reset_user_password.getpass.getpass", side_effect=["Abc1!", "Abc1!"]):
            with self.assertRaisesRegex(ValueError, "7"):
                _read_password("operator")

    def test_operator_login_and_wrong_password(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            wrong = client.post("/api/v1/auth/login", json={"username": "operator", "password": "wrong"})
            self.assertEqual(wrong.status_code, 401)
            ok = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["user"]["role"], "operator")

    def test_login_logout_cycle_preserves_valid_credentials(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            for _ in range(3):
                login = client.post(
                    "/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-password"},
                )
                self.assertEqual(login.status_code, 200)
                self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)
                logout = client.post(
                    "/api/v1/auth/logout",
                    headers={"X-CSRF-Token": login.json()["csrf_token"]},
                )
                self.assertEqual(logout.status_code, 200)
                self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_valid_login_replaces_stale_session_cookie(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app, cookies={"cotasync_session": "stale", "cotasync_csrf": "stale"})
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "operator", "password": "operator-password"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_protected_endpoint_without_login_returns_401(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            response = TestClient(app).post("/api/desktop-browser/view-token")
        self.assertEqual(response.status_code, 401)

    def test_operator_is_blocked_from_admin_config(self) -> None:
        with authenticated_client("operator") as client:
            response = client.put("/api/browser/config", json={"browser_mode": "desktop_browser"})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_admin_config(self) -> None:
        with authenticated_client("admin") as client:
            response = client.put("/api/browser/config", json={"browser_mode": "desktop_browser"})
        self.assertEqual(response.status_code, 200)

    def test_operator_can_create_desktop_view_token(self) -> None:
        with authenticated_client("operator") as client:
            response = client.post("/api/desktop-browser/view-token")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(response.json()["view_url"], str(response.headers))

    def test_existing_session_is_revoked_when_user_is_deactivated(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

            with SessionLocal.begin() as session:
                user = session.scalar(select(User).where(User.username == "operator"))
                assert user is not None
                user.active = False

            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
            relogin = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(relogin.status_code, 401)

    def test_reactivated_user_requires_new_session_after_auth_version_increment(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(login.status_code, 200)

            with SessionLocal.begin() as session:
                user = session.scalar(select(User).where(User.username == "operator"))
                assert user is not None
                user.active = False
                user.auth_version += 1
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

            with SessionLocal.begin() as session:
                user = session.scalar(select(User).where(User.username == "operator"))
                assert user is not None
                user.active = True
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

            relogin = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(relogin.status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_existing_session_is_revoked_when_password_changes(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

            reset_user_password("operator", "operator-new-password")

            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)
            old_login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(old_login.status_code, 401)
            new_login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-new-password"})
            self.assertEqual(new_login.status_code, 200)
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_auth_version_mismatch_is_rejected(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            token = create_session_token(AuthUser(username="operator", role="operator", auth_version=99))
            client = TestClient(app, cookies={"cotasync_session": token})
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_expired_token_is_rejected(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            issued_at = datetime.now(UTC) - timedelta(days=2)
            token = create_session_token(AuthUser(username="operator", role="operator", auth_version=1), now=issued_at)
            client = TestClient(app, cookies={"cotasync_session": token})
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_session_for_deleted_user_is_rejected(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(login.status_code, 200)

            with SessionLocal.begin() as session:
                user = session.scalar(select(User).where(User.username == "operator"))
                assert user is not None
                session.delete(user)

            self.assertEqual(client.get("/api/v1/auth/me").status_code, 401)

    def test_authorization_uses_current_database_role(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            token = create_session_token(AuthUser(username="operator", role="admin", auth_version=1))
            client = TestClient(app, cookies={"cotasync_session": token})
            response = client.put("/api/browser/config", json={"browser_mode": "desktop_browser"})
            self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
