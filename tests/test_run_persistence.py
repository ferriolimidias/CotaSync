from __future__ import annotations

import json
import unittest

from backend.services.action_runner import _safe_result_payload


class RunPersistenceSafetyTests(unittest.TestCase):
    def test_browser_page_in_diagnostics_is_json_safe(self) -> None:
        class PageLike:
            url = "https://example.test/result"

        payload = _safe_result_payload(
            {
                "status": "success",
                "current_url": PageLike(),
                "step_diagnostics": [{"page": PageLike()}],
                "dados_extraidos": {"resultado": "034"},
            }
        )

        self.assertIsNotNone(payload)
        json.dumps(payload)
        assert payload is not None
        self.assertEqual(payload["current_url"], {"type": "PageLike", "url": "https://example.test/result"})
        self.assertEqual(payload["dados_extraidos"]["resultado"], "034")
