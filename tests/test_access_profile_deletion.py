from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.db import Action, ActionVersion, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_profiles import AccessProfileError, active_access_profile_public, delete_access_profile
from backend.services.browser_providers import BrowserIdentitySession
from backend.services.execution_preflight import preflight_action_execution


def _system_and_profile() -> tuple[str, str]:
    suffix = uuid4().hex
    system_id = f"delete-system-{suffix}"
    profile_id = f"delete-profile-{suffix}"
    with SessionLocal.begin() as db:
        db.add(ExternalSystem(id=system_id, name=system_id, config={"entry_url": "https://entry.example.test"}))
        db.flush()
        db.add(ExternalAccessProfile(
            id=profile_id,
            tenant_id="default",
            external_system_id=system_id,
            display_name="Delete test",
            login_identifier=f"delete-{suffix}@example.test",
            active=True,
        ))
    return system_id, profile_id


def test_delete_unused_profile_removes_record_and_owned_storage(tmp_path, monkeypatch) -> None:
    _system_id, profile_id = _system_and_profile()
    monkeypatch.setenv("COTASYNC_ACCESS_PROFILE_STORAGE_DIR", str(tmp_path))
    storage_path = BrowserIdentitySession(SimpleNamespace(), profile_id).storage_path
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text("{}", encoding="utf-8")

    result = delete_access_profile(profile_id)

    assert result["status"] == "deleted"
    assert not storage_path.exists()
    with SessionLocal() as db:
        assert db.get(ExternalAccessProfile, profile_id) is None


def test_delete_referenced_profile_retires_without_breaking_history(tmp_path, monkeypatch) -> None:
    system_id, profile_id = _system_and_profile()
    action_id = f"delete-action-{uuid4().hex}"
    version_id = f"delete-version-{uuid4().hex}"
    monkeypatch.setenv("COTASYNC_ACCESS_PROFILE_STORAGE_DIR", str(tmp_path))
    storage_path = BrowserIdentitySession(SimpleNamespace(), profile_id).storage_path
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text("{}", encoding="utf-8")
    with SessionLocal.begin() as db:
        db.add(Action(id=action_id, key=action_id, name="Delete test", status="published", required_access_profile_id=profile_id))
        db.add(ActionVersion(
            id=version_id,
            action_id=action_id,
            version_number=1,
            status="published",
            definition={"run_start_strategy": "external_entry_each_run", "access_bootstrap": [{"event_type": "click", "selector": "#accept"}]},
            required_access_profile_id=profile_id,
            run_start_strategy="external_entry_each_run",
        ))
        db.flush()
        db.get(Action, action_id).published_version_id = version_id

    result = delete_access_profile(profile_id)

    assert result["status"] == "retired"
    assert not storage_path.exists()
    with SessionLocal() as db:
        profile = db.get(ExternalAccessProfile, profile_id)
        version = db.get(ActionVersion, version_id)
        assert profile is not None and profile.active is False and profile.validation_status == "retired"
        assert version is not None and version.required_access_profile_id == profile_id
    with pytest.raises(AccessProfileError):
        active_access_profile_public(profile_id)


def test_action_with_deleted_required_profile_fails_closed() -> None:
    _system_id, profile_id = _system_and_profile()
    action_id = f"blocked-action-{uuid4().hex}"
    version_id = f"blocked-version-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Action(id=action_id, key=action_id, name="Blocked test", status="published"))
        db.add(ActionVersion(id=version_id, action_id=action_id, version_number=1, status="published", definition={}, required_access_profile_id=profile_id, run_start_strategy="external_entry_each_run"))
        db.flush()
        db.get(Action, action_id).published_version_id = version_id
    delete_access_profile(profile_id)

    result = preflight_action_execution(SimpleNamespace(id=action_id), variables={})

    assert result["ok"] is False
    assert result["code"] == "required_access_profile_unavailable"
    assert "não está mais disponível" in result["message"]


def test_deleted_profile_does_not_fallback_to_another_profile() -> None:
    _system_id, deleted_id = _system_and_profile()
    _other_system_id, other_id = _system_and_profile()
    with SessionLocal.begin() as db:
        profile = db.get(ExternalAccessProfile, deleted_id)
        assert profile is not None
        profile.active = False
        action_id = f"no-fallback-action-{uuid4().hex}"
        version_id = f"no-fallback-version-{uuid4().hex}"
        db.add(Action(id=action_id, key=action_id, name="No fallback", status="published"))
        db.add(ActionVersion(id=version_id, action_id=action_id, version_number=1, status="published", definition={}, required_access_profile_id=deleted_id, run_start_strategy="external_entry_each_run"))
        db.flush()
        db.get(Action, action_id).published_version_id = version_id
    result = preflight_action_execution(SimpleNamespace(id=action_id), variables={})
    assert result["code"] == "required_access_profile_unavailable"
    assert other_id != deleted_id


def test_profile_storage_only_removes_deleted_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COTASYNC_ACCESS_PROFILE_STORAGE_DIR", str(tmp_path))
    _system_id, deleted_id = _system_and_profile()
    _other_system_id, other_id = _system_and_profile()
    deleted_path = BrowserIdentitySession(SimpleNamespace(), deleted_id).storage_path
    other_path = BrowserIdentitySession(SimpleNamespace(), other_id).storage_path
    deleted_path.parent.mkdir(parents=True, exist_ok=True)
    deleted_path.write_text("deleted", encoding="utf-8")
    other_path.write_text("preserve", encoding="utf-8")

    delete_access_profile(deleted_id)

    assert not deleted_path.exists()
    assert other_path.read_text(encoding="utf-8") == "preserve"


def test_deleted_profile_not_selectable() -> None:
    _system_id, profile_id = _system_and_profile()
    with SessionLocal.begin() as db:
        profile = db.get(ExternalAccessProfile, profile_id)
        assert profile is not None
        profile.active = False

    with pytest.raises(AccessProfileError):
        active_access_profile_public(profile_id)
