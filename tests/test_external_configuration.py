from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.api.v1 import _external_configuration_diagnostics


class ExternalConfigurationDiagnosticsTests(unittest.TestCase):
    def test_external_entry_configuration_does_not_require_live_system_or_list_binding(self) -> None:
        config = {
            "id": "system-a",
            "external_system_name": "Sistema A",
            "entry_url": "https://login.example.test/entry",
            "run_start_strategy": "external_entry_each_run",
            "expected_system_host": "app.example.test",
        }
        profile = {"id": "profile-a", "active": True, "external_system_id": "system-a"}
        with patch("backend.api.v1.list_access_profiles", return_value=[profile]):
            result = _external_configuration_diagnostics(config)
        self.assertTrue(result["complete"])
        self.assertEqual(result["missing_fields"], [])

    def test_missing_entry_and_profile_are_reported_separately(self) -> None:
        config = {
            "id": "system-a",
            "external_system_name": "Sistema A",
            "run_start_strategy": "external_entry_each_run",
            "expected_system_host": "app.example.test",
        }
        with patch("backend.api.v1.list_access_profiles", return_value=[]):
            result = _external_configuration_diagnostics(config)
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing_fields"], ["entry_url", "no_access_profile"])

    def test_persistent_strategy_does_not_require_external_entry_or_profile(self) -> None:
        config = {
            "id": "system-a",
            "external_system_name": "Sistema A",
            "run_start_strategy": "persistent_graph_reentry",
            "expected_system_host": "app.example.test",
        }
        with patch("backend.api.v1.list_access_profiles", return_value=[]):
            result = _external_configuration_diagnostics(config)
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
