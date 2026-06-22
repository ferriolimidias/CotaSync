from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.services.browser_providers import (
    BrowserProviderError,
    BrowserlessProvider,
    DesktopBrowserProvider,
    browser_provider,
    normalize_browser_mode,
)


class BrowserProvidersTest(unittest.TestCase):
    def test_modes_are_explicit(self) -> None:
        self.assertEqual(normalize_browser_mode("browserless"), "browserless")
        self.assertEqual(normalize_browser_mode("desktop_browser"), "desktop_browser")
        with self.assertRaises(BrowserProviderError):
            normalize_browser_mode("stealth")

    def test_provider_selection(self) -> None:
        self.assertIsInstance(browser_provider("browserless"), BrowserlessProvider)
        self.assertIsInstance(browser_provider("desktop_browser"), DesktopBrowserProvider)

    def test_browserless_tracking_url_is_unchanged(self) -> None:
        with patch.dict(os.environ, {"BROWSERLESS_URL": "ws://browserless:3000?token=test"}):
            result = BrowserlessProvider.websocket_url("abc-def")
        self.assertIn("token=test", result)
        self.assertIn("trackingId=cotasync-abcdef", result)
        self.assertIn("timeout=600000", result)


if __name__ == "__main__":
    unittest.main()
