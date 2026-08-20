from __future__ import annotations

import tests  # noqa: F401

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, Response

from backend.api.desktop_browser import create_desktop_view_token, validate_desktop_view_token
from backend.db import DesktopViewToken as DbDesktopViewToken, SessionLocal
from backend.services.desktop_view_tokens import create_token, mask_token, validate_token


class DesktopViewTokensTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "COTASYNC_DESKTOP_VIEW_PUBLIC_BASE_URL": (
                    "https://desktop-cotasync.ferriolimidias.com.br"
                ),
                "COTASYNC_DESKTOP_VIEW_TOKEN_TTL_SECONDS": "1800",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def test_create_and_validate_before_expiry(self) -> None:
        now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
        created = create_token(now=now)
        self.assertTrue(validate_token(created.token, now=now + timedelta(minutes=29)))
        self.assertEqual(created.ttl_seconds, 1800)

    def test_invalid_token_fails(self) -> None:
        self.assertFalse(validate_token("invalid-token"))
        with self.assertRaises(HTTPException) as raised:
            validate_desktop_view_token(Response(), token="invalid-token")
        self.assertEqual(raised.exception.status_code, 403)

    def test_expired_token_fails(self) -> None:
        now = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
        created = create_token(ttl_seconds=10, now=now)
        self.assertFalse(validate_token(created.token, now=now + timedelta(seconds=11)))

    def test_endpoint_returns_public_url_and_valid_token(self) -> None:
        response = Response()
        payload = create_desktop_view_token(response)
        parsed = urlsplit(str(payload["view_url"]))
        query = parse_qs(parsed.query)
        token = query["token"][0]
        self.assertEqual(parsed.netloc, "desktop-cotasync.ferriolimidias.com.br")
        self.assertEqual(parsed.path, "/vnc.html")
        self.assertEqual(query["autoconnect"], ["1"])
        self.assertEqual(query["resize"], ["scale"])
        self.assertTrue(validate_token(token))
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_token_is_masked_and_not_stored_in_clear(self) -> None:
        created = create_token()
        report_line = f"view_token={mask_token(created.token)}"
        self.assertNotIn(created.token, report_line)
        with SessionLocal() as session:
            digests = [row.digest for row in session.query(DbDesktopViewToken).all()]
        self.assertTrue(digests)
        self.assertNotIn(created.token, digests)


if __name__ == "__main__":
    unittest.main()
