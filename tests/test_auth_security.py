from __future__ import annotations

import tests  # noqa: F401

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from tests.auth_helpers import TEST_AUTH_ENV, authenticated_client


class AuthSecurityTests(unittest.TestCase):
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

    def test_operator_login_and_wrong_password(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            wrong = client.post("/api/v1/auth/login", json={"username": "operator", "password": "wrong"})
            self.assertEqual(wrong.status_code, 401)
            ok = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["user"]["role"], "operator")

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


if __name__ == "__main__":
    unittest.main()
