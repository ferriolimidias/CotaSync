from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


TEST_AUTH_ENV = {
    "COTASYNC_COOKIE_SECURE": "false",
    "COTASYNC_SESSION_SECRET": "test-session-secret",
    "COTASYNC_ADMIN_USERNAME": "admin",
    "COTASYNC_ADMIN_PASSWORD": "admin-password",
    "COTASYNC_OPERATOR_USERNAME": "operator",
    "COTASYNC_OPERATOR_PASSWORD": "operator-password",
}


@contextmanager
def authenticated_client(role: str = "operator") -> Iterator[TestClient]:
    with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
        client = TestClient(app)
        username = "admin" if role == "admin" else "operator"
        password = "admin-password" if role == "admin" else "operator-password"
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        csrf = response.json()["csrf_token"]
        client.headers.update({"X-CSRF-Token": csrf})
        yield client
