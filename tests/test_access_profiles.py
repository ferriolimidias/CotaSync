from __future__ import annotations

import unittest
from uuid import uuid4

import tests  # noqa: F401
from backend.db import Action, ActionVersion, ClientList, ExternalSystem, SessionLocal
from backend.api.v1 import _external_system_config_payload
from backend.services.access_profiles import AccessProfileError, create_access_profile, list_access_profiles, record_profile_validation, update_access_profile, validate_access_bootstrap
from backend.services.external_systems import load_current_external_system
from backend.services.session_guardian import classify_microsoft_auth_state, detect_microsoft_account_picker


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

    def test_last_validation_status_is_durable_and_returned_by_list(self) -> None:
        profile = create_access_profile(external_system_id=self.system_id, display_name="Durable", login_identifier=f"durable-{uuid4()}@example.test")
        updated = record_profile_validation(profile["id"], status="available", reason="profile_available")
        self.assertEqual(updated["validation_status"], "available")
        self.assertTrue(updated["last_validated_at"])
        listed = next(item for item in list_access_profiles() if item["id"] == profile["id"])
        self.assertEqual(listed["validation_status"], "available")
        self.assertEqual(listed["session_status"], "available")

        for status, reason in (("reauth_required", "mfa_required"), ("not_found", "account_not_found")):
            record_profile_validation(profile["id"], status=status, reason=reason)
            current = next(item for item in list_access_profiles() if item["id"] == profile["id"])
            self.assertEqual(current["validation_status"], status)
            self.assertEqual(current["last_validation_reason"], reason)

        self.assertEqual(list_access_profiles(tenant_id="other-tenant"), [])
        with self.assertRaises(AccessProfileError):
            record_profile_validation(profile["id"], status="available", tenant_id="other-tenant")

    def test_picker_uses_identifier_not_dom_order(self) -> None:
        text = "Pick an account João Signed in Priscila Susin D0004267@rdmz.com.br Signed in Maria Signed in"
        result = detect_microsoft_account_picker(text, ["D0004267@rdmz.com.br"])
        self.assertTrue(result["profile_available"])
        self.assertEqual(result["available_identifiers"], ["D0004267@rdmz.com.br"])

    def test_missing_required_profile_is_not_a_fallback(self) -> None:
        result = detect_microsoft_account_picker("Pick an account João Signed in Maria Signed in", ["D0004267@rdmz.com.br"])
        self.assertFalse(result["profile_available"])

    def test_multiple_profiles_match_by_identifier_after_reordering(self) -> None:
        text = "Pick an account Maria Signed in João Signed in Priscila Susin D0004267@rdmz.com.br Signed in"
        result = detect_microsoft_account_picker(text, ["D0004267@rdmz.com.br", "joao@example.test", "maria@example.test"])
        self.assertEqual(result["available_identifiers"], ["D0004267@rdmz.com.br"])

    def test_manual_reauthentication_is_not_session_disconnect(self) -> None:
        self.assertEqual(classify_microsoft_auth_state("Enter password"), "password_required")
        self.assertEqual(classify_microsoft_auth_state("Approve sign in request"), "mfa_required")

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

    def test_legacy_global_identifier_is_not_returned_by_new_system_payload(self) -> None:
        config = load_current_external_system()
        payload = _external_system_config_payload(config)
        self.assertNotIn("access_profile_email_or_identifier", payload)


if __name__ == "__main__":
    unittest.main()
