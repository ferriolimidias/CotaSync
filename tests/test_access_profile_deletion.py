from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.db import AccessCycle, Action, ActionVersion, ClientList, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_profiles import AccessProfileError, active_access_profile_public, assign_action_access_profile, create_access_profile, delete_access_profile, list_access_profiles
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


def test_delete_referenced_profile_hard_deletes_and_unlinks_history(tmp_path, monkeypatch) -> None:
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

    assert result["status"] == "deleted"
    assert not storage_path.exists()
    with SessionLocal() as db:
        version = db.get(ActionVersion, version_id)
        assert db.get(ExternalAccessProfile, profile_id) is None
        assert version is not None and version.required_access_profile_id is None
    with pytest.raises(AccessProfileError):
        active_access_profile_public(profile_id)


def test_recreate_same_identifier_after_delete() -> None:
    system_id, profile_id = _system_and_profile()
    with SessionLocal.begin() as db:
        old = db.get(ExternalAccessProfile, profile_id)
        assert old is not None
        identifier = old.login_identifier
    delete_access_profile(profile_id)
    recreated = create_access_profile(external_system_id=system_id, display_name="New profile", login_identifier=identifier)
    assert recreated["login_identifier"] == identifier


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
    assert result["code"] == "required_access_profile_not_assigned"
    assert "não possui usuário de acesso" in result["message"]


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
    assert result["code"] == "required_access_profile_not_assigned"
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


def test_active_profile_visible() -> None:
    _system_id, profile_id = _system_and_profile()
    assert profile_id in {item["id"] for item in list_access_profiles()}


def test_retired_profile_hidden() -> None:
    _system_id, profile_id = _system_and_profile()
    with SessionLocal.begin() as db:
        profile = db.get(ExternalAccessProfile, profile_id)
        assert profile is not None
        profile.active = False
    assert profile_id not in {item["id"] for item in list_access_profiles()}


def test_delete_refreshes_operational_list_and_preserves_history() -> None:
    _system_id, profile_id = _system_and_profile()
    with SessionLocal.begin() as db:
        db.add(ClientList(id=f"delete-list-{uuid4().hex}", tenant_id="default", name="Referenced list", access_profile_id=profile_id, active=True))
    result = delete_access_profile(profile_id)
    assert result["status"] == "deleted"
    assert profile_id not in {item["id"] for item in list_access_profiles()}
    with SessionLocal() as db:
        assert db.get(ExternalAccessProfile, profile_id) is None


def test_explicit_rebind_restores_action_preflight() -> None:
    system_id, old_profile_id = _system_and_profile()
    action_id = f"rebind-action-{uuid4().hex}"
    version_id = f"rebind-version-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Action(id=action_id, key=action_id, name="Rebind", status="published", required_access_profile_id=old_profile_id))
        db.add(ActionVersion(id=version_id, action_id=action_id, version_number=1, status="published", definition={"external_system_id": system_id, "access_bootstrap": [{"event_type": "click", "selector": "#accept"}]}, required_access_profile_id=old_profile_id, run_start_strategy="external_entry_each_run"))
        db.flush()
        db.get(Action, action_id).published_version_id = version_id
    delete_access_profile(old_profile_id)
    new_profile = create_access_profile(external_system_id=system_id, display_name="Rebound", login_identifier=f"rebound-{uuid4().hex}@example.test")
    binding = assign_action_access_profile(action_id, new_profile["id"])
    assert binding["access_profile_id"] == new_profile["id"]
    result = preflight_action_execution(SimpleNamespace(id=action_id), variables={})
    assert result["ok"] is True


def test_references_unlinked_and_active_cycle_cancelled() -> None:
    system_id, profile_id = _system_and_profile()
    cycle_id = f"delete-cycle-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(AccessCycle(id=cycle_id, external_system_id=system_id, access_profile_id=profile_id, entry_url="https://entry.example.test", status="starting", stage="access_start", events=[]))
    delete_access_profile(profile_id)
    with SessionLocal() as db:
        cycle = db.get(AccessCycle, cycle_id)
        assert cycle is not None
        assert cycle.access_profile_id is None
        assert cycle.status == "cancelled"
        assert cycle.error_code == "ACCESS_PROFILE_DELETED"
