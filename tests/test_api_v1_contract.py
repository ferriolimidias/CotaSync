from __future__ import annotations

import tests  # noqa: F401

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.db import Batch as DbBatch, BatchItem, SessionLocal, WorkerInstance
from backend.main import app
from tests.auth_helpers import TEST_AUTH_ENV, authenticated_client
from tests.test_batch_runner import fake_action


class ApiV1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        with SessionLocal.begin() as session:
            session.query(WorkerInstance).delete()
            session.query(BatchItem).delete()
            session.query(DbBatch).delete()

    def test_auth_v1_uses_cookie_session(self) -> None:
        with patch.dict("os.environ", TEST_AUTH_ENV, clear=False):
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "operator-password"})
            self.assertEqual(login.status_code, 200)
            self.assertIn("httponly", login.headers.get("set-cookie", "").lower())
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)

    def test_v1_unauthenticated_error_shape(self) -> None:
        response = TestClient(app).get("/api/v1/dashboard")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "AUTH_REQUIRED")

    def test_dashboard_clients_actions_reports_and_worker_contracts(self) -> None:
        with authenticated_client("operator") as client, patch(
            "backend.api.v1.latest_worker_status",
            return_value={"online": True, "status": "idle", "browser_lock": True},
        ):
            self.assertEqual(client.get("/api/v1/dashboard").status_code, 200)
            self.assertIn("clients", client.get("/api/v1/clients").json())
            actions = client.get("/api/v1/actions")
            self.assertEqual(actions.status_code, 200)
            self.assertIn("actions", actions.json())
            self.assertEqual(client.get("/api/v1/reports/runs").status_code, 200)
            self.assertEqual(client.get("/api/v1/reports/batches").status_code, 200)
            worker = client.get("/api/v1/worker/status")
            self.assertEqual(worker.status_code, 200)
            self.assertTrue(worker.json()["worker"]["online"])

    def test_browser_external_session_and_learning_contracts(self) -> None:
        fake_health = {"cdp_reachable": True, "version": "test"}
        with authenticated_client("operator") as client, patch("backend.api.v1.desktop_browser_health", return_value=fake_health):
            self.assertEqual(client.get("/api/v1/learning/capabilities").status_code, 200)
            self.assertEqual(client.get("/api/v1/browser/status").status_code, 200)
            self.assertEqual(client.post("/api/v1/browser/ensure-ready").status_code, 200)
            token = client.post("/api/v1/browser/view-token")
            self.assertEqual(token.status_code, 200)
            self.assertIn("view_url", token.json())
            self.assertEqual(client.get("/api/v1/external-session/status").status_code, 200)

    def test_batches_v1_idempotency_conflict_and_polling(self) -> None:
        payload = {
            "action_id": "numero-de-parcelas-pagas",
            "rows": [{"grupo": "935", "grupo_2": "110", "grupo_3": "00"}],
            "delay_between_rows_seconds": 3,
        }
        with authenticated_client("operator") as client, patch("backend.services.batch_runner.find_action", return_value=fake_action()):
            first = client.post("/api/v1/batches", json=payload, headers={"Idempotency-Key": "api-v1-key"})
            self.assertEqual(first.status_code, 200, first.text)
            second = client.post("/api/v1/batches", json=payload, headers={"Idempotency-Key": "api-v1-key"})
            self.assertEqual(first.json()["batch"]["batch_id"], second.json()["batch"]["batch_id"])
            changed = dict(payload)
            changed["rows"] = [{"grupo": "935", "grupo_2": "999", "grupo_3": "00"}]
            conflict = client.post("/api/v1/batches", json=changed, headers={"Idempotency-Key": "api-v1-key"})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["error"]["code"], "BATCH_IDEMPOTENCY_CONFLICT")
            batch_id = first.json()["batch"]["batch_id"]
            self.assertEqual(client.get(f"/api/v1/batches/{batch_id}").status_code, 200)
            self.assertEqual(client.get(f"/api/v1/batches/{batch_id}/results").status_code, 200)

    def test_diagnostics_requires_admin(self) -> None:
        fake_health = {"cdp_reachable": True}
        with authenticated_client("operator") as operator:
            self.assertEqual(operator.get("/api/v1/diagnostics/system").status_code, 403)
        with authenticated_client("admin") as admin, patch("backend.api.v1.desktop_browser_health", return_value=fake_health):
            self.assertEqual(admin.get("/api/v1/diagnostics/system").status_code, 200)


if __name__ == "__main__":
    unittest.main()
