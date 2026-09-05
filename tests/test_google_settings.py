import json
import os
import unittest
from unittest.mock import patch

from backend.db import GoogleSettings, SessionLocal
from backend.services.google_settings import effective_credentials, public_settings, remove_credentials, save_credentials, validate_service_account


VALID = {
    "type": "service_account",
    "project_id": "cotasync-test",
    "private_key_id": "key-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----\n",
    "client_email": "cotasync-sheets@cotasync-test.iam.gserviceaccount.com",
    "client_id": "123",
    "token_uri": "https://oauth2.googleapis.com/token",
}


class GoogleSettingsSecurityTests(unittest.TestCase):
    def setUp(self):
        remove_credentials()

    def tearDown(self):
        remove_credentials()

    def test_valid_credential_is_encrypted_and_public_metadata_is_safe(self):
        result = save_credentials(json.dumps(VALID))
        self.assertTrue(result["configured"])
        self.assertEqual(result["client_email"], VALID["client_email"])
        self.assertNotIn("private_key", result)
        with SessionLocal() as db:
            row = db.query(GoogleSettings).filter_by(tenant_id="default").one()
            self.assertNotIn("BEGIN PRIVATE KEY", row.credentials_encrypted)
        credentials, source = effective_credentials()
        self.assertEqual(source, "stored")
        self.assertEqual(credentials["client_email"], VALID["client_email"])

    def test_invalid_type_and_missing_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_service_account(json.dumps({**VALID, "type": "user"}))
        with self.assertRaises(ValueError):
            validate_service_account(json.dumps({key: value for key, value in VALID.items() if key != "private_key"}))

    def test_environment_is_fallback_without_persisting_secret(self):
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(VALID)}, clear=False):
            remove_credentials()
            result = public_settings()
            self.assertEqual(result["source"], "environment")
            self.assertEqual(result["client_email"], VALID["client_email"])

    def test_replacement_invalid_does_not_remove_existing(self):
        save_credentials(json.dumps(VALID))
        with self.assertRaises(ValueError):
            save_credentials("{}")
        credentials, _source = effective_credentials()
        self.assertEqual(credentials["client_email"], VALID["client_email"])


if __name__ == "__main__":
    unittest.main()
