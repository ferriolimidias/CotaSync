from __future__ import annotations

import unittest

from backend.services.browserless_urls import public_devtools_host, public_devtools_url


class PublicBrowserlessUrlTest(unittest.TestCase):
    def test_internal_websocket_is_replaced_by_public_wss(self) -> None:
        result = public_devtools_url(
            "ws://0.0.0.0:3000/devtools/page/ABC",
            "https://browserless-cotasync.ferriolimidias.com.br",
        )

        self.assertEqual(
            result,
            "https://browserless-cotasync.ferriolimidias.com.br/devtools/inspector.html"
            "?wss=browserless-cotasync.ferriolimidias.com.br/devtools/page/ABC",
        )
        self.assertNotIn("0.0.0.0", result)
        self.assertNotIn("127.0.0.1", result)
        self.assertEqual(
            public_devtools_host(result),
            "browserless-cotasync.ferriolimidias.com.br",
        )

    def test_local_demo_uses_ws_and_localhost(self) -> None:
        result = public_devtools_url(
            "ws://cotasync_test_browserless:3000/devtools/page/LOCAL",
            "http://localhost:3010",
        )

        self.assertEqual(
            result,
            "http://localhost:3010/devtools/inspector.html"
            "?ws=localhost:3010/devtools/page/LOCAL",
        )
        self.assertNotIn("cotasync_test_browserless", result)


if __name__ == "__main__":
    unittest.main()
