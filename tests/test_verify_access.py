from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import tests  # noqa: F401
from backend.api.v1 import external_session_status, external_session_validate
from backend.db import ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_profiles import create_access_profile


class VerifyAccessTests(unittest.TestCase):
    def test_passive_unknown_does_not_downgrade_available_profile(self) -> None:
        system_id = f"passive-system-{uuid4()}"
        with SessionLocal.begin() as db:
            db.add(ExternalSystem(id=system_id, name=f"Passive {uuid4()}", config={"entry_url": "https://example.test/entry", "run_start_strategy": "external_entry_each_run"}))
        profile = create_access_profile(external_system_id=system_id, display_name="Priscila", login_identifier=f"priscila-{uuid4()}@example.test")
        from backend.services.access_profiles import record_profile_validation
        record_profile_validation(profile["id"], status="available", reason="profile_available")
        observation = SimpleNamespace(browser_available=True, page_available=True, body_text="", deep=False, current_url="https://login.microsoftonline.com/common/oauth2")
        config = {
            "id": system_id,
            "external_system_name": "Passive",
            "external_login_url": "https://login.microsoftonline.com/common/oauth2",
            "entry_url": "https://example.test/entry",
            "expected_system_host": "example.test",
            "run_start_strategy": "external_entry_each_run",
            "microsoft_hosts": ["login.microsoftonline.com"],
        }
        try:
            with patch("backend.api.v1.load_current_external_system", return_value=config), patch(
                "backend.api.v1.browser_observation_service.observe", new=AsyncMock(return_value=observation)
            ) as observe:
                for _ in range(3):
                    result = asyncio.run(external_session_status())
                    self.assertEqual(result["external_session"]["microsoft_status"], "available")
            self.assertEqual(observe.await_count, 3)
        finally:
            with SessionLocal.begin() as db:
                db.query(ExternalAccessProfile).filter(ExternalAccessProfile.id == profile["id"]).delete(synchronize_session=False)
                db.query(ExternalSystem).filter(ExternalSystem.id == system_id).delete(synchronize_session=False)

    def test_verify_access_persists_each_profile_from_one_observation(self) -> None:
        system_id = f"verify-system-{uuid4()}"
        with SessionLocal.begin() as db:
            db.add(ExternalSystem(id=system_id, name=f"Verify {uuid4()}", config={"entry_url": "https://example.test/entry", "run_start_strategy": "external_entry_each_run"}))
        available = create_access_profile(external_system_id=system_id, display_name="Priscila", login_identifier=f"priscila-{uuid4()}@example.test")
        missing = create_access_profile(external_system_id=system_id, display_name="Joao", login_identifier=f"joao-{uuid4()}@example.test")
        observation = SimpleNamespace(
            browser_available=True,
            page_available=True,
            body_text=f"Pick an account Priscila {available['login_identifier']} Signed in",
            deep=True,
            current_url="https://login.microsoftonline.com/common/oauth2",
        )
        config = {
            "id": system_id,
            "external_system_name": "Verify",
            "external_login_url": "https://login.microsoftonline.com/common/oauth2",
            "entry_url": "https://example.test/entry",
            "expected_system_host": "example.test",
            "run_start_strategy": "external_entry_each_run",
            "microsoft_hosts": ["login.microsoftonline.com"],
        }
        try:
            with patch("backend.api.v1.load_current_external_system", return_value=config), patch(
                "backend.api.v1.browser_observation_service.observe_deep", new=AsyncMock(return_value=observation)
            ) as observe:
                result = asyncio.run(external_session_validate())
            profiles = {item["id"]: item for item in result["profiles"]}
            self.assertEqual(profiles[available["id"]]["validation_status"], "available")
            self.assertEqual(profiles[missing["id"]]["validation_status"], "not_found")
            self.assertEqual(result["external_session"]["microsoft_status"], "available")
            self.assertEqual(result["external_session"]["available_profile_count"], 1)
            self.assertEqual(result["external_session"]["access_profile_count"], 2)
            observe.assert_awaited_once()
        finally:
            with SessionLocal.begin() as db:
                db.query(ExternalAccessProfile).filter(ExternalAccessProfile.id.in_([available["id"], missing["id"]])).delete(synchronize_session=False)
                db.query(ExternalSystem).filter(ExternalSystem.id == system_id).delete(synchronize_session=False)


if __name__ == "__main__":
    unittest.main()
