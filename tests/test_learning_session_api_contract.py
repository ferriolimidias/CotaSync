import asyncio
from unittest.mock import AsyncMock, patch

from backend.api.v1 import demo_session_manager, learning_get_session


def test_learning_get_preserves_access_cycle_and_workspace_contract():
    snapshot = {
        "id": "learning-a", "access_cycle_id": "cycle-a",
        "access_profile_id": "profile-a", "live_url": "/workspace/target-a",
        "status": "aguardando_acesso", "recording": False,
        "outputs": [], "target_id": "target-a",
    }
    diagnostics = {"steps_count": 0, "recording": False, "recorder_installed": False}
    with patch.object(demo_session_manager, "ensure_session", AsyncMock()), patch.object(
        demo_session_manager, "status", AsyncMock(return_value=dict(snapshot))
    ), patch.object(demo_session_manager, "recording_diagnostics", AsyncMock(return_value=diagnostics)):
        response = asyncio.run(learning_get_session("learning-a", None))
    assert response["session"] == {**snapshot, **diagnostics}

