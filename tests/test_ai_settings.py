import os
import unittest
from unittest.mock import patch

from backend.services.ai_settings import effective_settings, public_settings, remove_key, save_settings


class AISettingsSecurityTests(unittest.TestCase):
    def setUp(self):
        current = effective_settings()
        self.original = {
            "enabled": current.enabled,
            "provider": current.provider,
            "model": current.model,
            "base_url": current.base_url,
        }
        remove_key()

    def tearDown(self):
        remove_key()
        save_settings(**self.original, api_key=None)

    def test_public_settings_never_contains_secret(self):
        save_settings(**self.original, api_key="synthetic-secret")
        public = public_settings()
        self.assertNotIn("api_key", public)
        self.assertTrue(public["api_key_configured"])

    def test_empty_update_preserves_stored_key_and_disabled_does_not_remove_it(self):
        save_settings(enabled=True, provider="openai_compatible", model="test-model", base_url="", api_key="synthetic-secret")
        save_settings(enabled=False, provider="openai_compatible", model="test-model", base_url="", api_key=None)
        self.assertEqual(effective_settings().api_key, "synthetic-secret")
        self.assertFalse(effective_settings().enabled)

    def test_environment_key_is_fallback(self):
        remove_key()
        with patch.dict(os.environ, {"AI_API_KEY": "environment-secret"}, clear=False):
            settings = effective_settings()
        self.assertEqual(settings.api_key_source, "AI_API_KEY")
        self.assertEqual(settings.api_key, "environment-secret")

    def test_explicit_key_replacement_is_encrypted_at_rest(self):
        save_settings(**self.original, api_key="synthetic-secret")
        from backend.db import AISettings, SessionLocal
        with SessionLocal() as db:
            row = db.get(AISettings, 1)
            self.assertIsNotNone(row.api_key_encrypted)
            self.assertNotIn("synthetic-secret", row.api_key_encrypted)


if __name__ == "__main__":
    unittest.main()
