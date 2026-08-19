from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.services.browser_providers import (
    BrowserProviderError,
    DesktopBrowserProvider,
    browser_provider,
    configured_browser_mode,
    normalize_browser_mode,
)


class BrowserProvidersTest(unittest.TestCase):
    def test_single_supported_mode(self) -> None:
        self.assertEqual(normalize_browser_mode("desktop_browser"), "desktop_browser")
        self.assertEqual(normalize_browser_mode(""), "desktop_browser")
        with self.assertRaises(BrowserProviderError):
            normalize_browser_mode("stealth")

    def test_provider_selection_is_always_desktop(self) -> None:
        self.assertIsInstance(browser_provider("desktop_browser"), DesktopBrowserProvider)
        self.assertIsInstance(browser_provider(), DesktopBrowserProvider)

    def test_invalid_config_falls_back_to_desktop(self) -> None:
        with patch.dict("os.environ", {"COTASYNC_BROWSER_MODE": "invalid"}, clear=False):
            self.assertEqual(configured_browser_mode(), "desktop_browser")


if __name__ == "__main__":
    unittest.main()
