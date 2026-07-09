from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.demo_session import demo_session_manager
from frontend.api_client import operator_clear_active, operator_press_key, operator_type_active


ROOT = Path(__file__).resolve().parent.parent


class OperatorLoginControlsTests(unittest.TestCase):
    def test_insert_active_endpoint_accepts_normal_text_numbers_and_special_chars(self) -> None:
        value = "user.123+teste@example.com"
        with patch.object(
            demo_session_manager,
            "operator_insert_active",
            new=AsyncMock(return_value={"operation": "insert_active_text", "typed_chars": len(value), "sensitive": False}),
        ) as mocked:
            response = TestClient(app).post(
                "/api/demo/sessions/session-1/operator/insert-active",
                json={"value": value, "sensitive": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["operator"]["typed_chars"], len(value))
        mocked.assert_awaited_once_with("session-1", value, sensitive=False)

    def test_sensitive_insert_active_never_returns_text(self) -> None:
        secret = "Senha#123456"
        with patch.object(
            demo_session_manager,
            "operator_insert_active",
            new=AsyncMock(return_value={"operation": "insert_active_text", "typed_chars": len(secret), "sensitive": True}),
        ) as mocked:
            response = TestClient(app).post(
                "/api/demo/sessions/session-1/operator/insert-active",
                json={"value": secret, "sensitive": True},
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["operator"]["sensitive"])
        self.assertEqual(body["operator"]["typed_chars"], len(secret))
        self.assertNotIn(secret, str(body))
        mocked.assert_awaited_once_with("session-1", secret, sensitive=True)

    def test_press_enter_and_tab_endpoints(self) -> None:
        with patch.object(
            demo_session_manager,
            "operator_press",
            new=AsyncMock(return_value={"operation": "press_key", "key": "Enter"}),
        ) as mocked:
            enter = TestClient(app).post("/api/demo/sessions/session-1/operator/press", json={"key": "Enter"})
            tab = TestClient(app).post("/api/demo/sessions/session-1/operator/press", json={"key": "Tab"})

        self.assertEqual(enter.status_code, 200)
        self.assertEqual(tab.status_code, 200)
        self.assertEqual(mocked.await_args_list[0].args, ("session-1", "Enter"))
        self.assertEqual(mocked.await_args_list[1].args, ("session-1", "Tab"))

    def test_clear_active_endpoint(self) -> None:
        with patch.object(
            demo_session_manager,
            "operator_clear_active",
            new=AsyncMock(return_value={"operation": "clear_active"}),
        ) as mocked:
            response = TestClient(app).post("/api/demo/sessions/session-1/operator/clear-active")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["operator"]["operation"], "clear_active")
        mocked.assert_awaited_once_with("session-1")

    def test_frontend_exposes_login_operator_controls(self) -> None:
        source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")

        self.assertIn("Modo operador para login", source)
        self.assertIn("Texto/login", source)
        self.assertIn("Senha ou texto sensível", source)
        self.assertIn("Digitar senha no campo ativo", source)
        self.assertIn("Limpar campo ativo", source)

    def test_api_client_exposes_operator_helpers(self) -> None:
        self.assertTrue(callable(operator_type_active))
        self.assertTrue(callable(operator_press_key))
        self.assertTrue(callable(operator_clear_active))


if __name__ == "__main__":
    unittest.main()
