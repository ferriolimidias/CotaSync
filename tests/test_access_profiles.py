from __future__ import annotations

import unittest
from uuid import uuid4

import tests  # noqa: F401
from backend.db import Action, ActionVersion, ClientList, ExternalSystem, SessionLocal
from backend.services.access_profiles import AccessProfileError, create_access_profile, list_access_profiles, update_access_profile, validate_access_bootstrap
from backend.services.session_guardian import detect_microsoft_account_picker


class AccessProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system_id = f"system-{uuid4()}"
        with SessionLocal.begin() as db:
            db.add(ExternalSystem(id=self.system_id, name=f"Sistema {uuid4()}", config={"entry_url": "https://example.test/entry", "run_start_strategy": "external_entry_each_run"}))

    def test_profile_is_stable_and_does_not_store_secrets(self) -> None:
        profile = create_access_profile(external_system_id=self.system_id, display_name="Priscila Susin", login_identifier="D0004267@rdmz.com.br")
        self.assertTrue(profile["id"])
        self.assertNotIn("password", profile)
        self.assertNotIn("token", profile)
        listed = list_access_profiles()
        self.assertIn(profile["id"], {item["id"] for item in listed})
        renamed = update_access_profile(profile["id"], display_name="Priscila")
        self.assertEqual(renamed["id"], profile["id"])
        self.assertEqual(renamed["display_name"], "Priscila")

    def test_picker_uses_identifier_not_dom_order(self) -> None:
        text = "Pick an account João Signed in Priscila Susin D0004267@rdmz.com.br Signed in Maria Signed in"
        result = detect_microsoft_account_picker(text, ["D0004267@rdmz.com.br"])
        self.assertTrue(result["profile_available"])
        self.assertEqual(result["available_identifiers"], ["D0004267@rdmz.com.br"])

    def test_missing_required_profile_is_not_a_fallback(self) -> None:
        result = detect_microsoft_account_picker("Pick an account João Signed in Maria Signed in", ["D0004267@rdmz.com.br"])
        self.assertFalse(result["profile_available"])

    def test_bootstrap_rejects_ordinal_account_selector(self) -> None:
        result = validate_access_bootstrap({"access_bootstrap": [{"selector": ".account:nth-child(1)"}]}, profile_id="profile")
        self.assertFalse(result["valid"])
        self.assertEqual(result["code"], "access_bootstrap_ordinal_selector")

    def test_bootstrap_requires_captured_evidence(self) -> None:
        result = validate_access_bootstrap({}, profile_id="profile")
        self.assertFalse(result["valid"])
        self.assertEqual(result["code"], "access_bootstrap_missing")

    def test_profile_deactivation_with_list_dependency_is_blocked(self) -> None:
        profile = create_access_profile(external_system_id=self.system_id, display_name="Priscila", login_identifier=f"p-{uuid4()}@example.test")
        with SessionLocal.begin() as db:
            db.add(ClientList(id=f"list-{uuid4()}", tenant_id="default", name=f"Lista {uuid4()}", access_profile_id=profile["id"], active=True))
        with self.assertRaises(AccessProfileError):
            update_access_profile(profile["id"], active=False)


if __name__ == "__main__":
    unittest.main()
