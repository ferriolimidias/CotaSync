from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["pending", "running", "success", "error", "cancelled"]
RunMode = Literal["sync", "async"]
RunOrigin = Literal["operational", "smoke", "validation", "automated_test", "migration"]


class ActionRunRequest(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    mode: RunMode = "sync"
    requested_by: str = "api"
    session_id: str | None = None
    run_origin: RunOrigin = "operational"
    batch_id: str | None = None


class RunRecord(BaseModel):
    id: str
    action_id: str
    action_key: str
    action_version_id: str | None = None
    status: RunStatus
    mode: RunMode = "sync"
    run_type: str = "action_run"
    run_origin: RunOrigin = "operational"
    requested_by: str = "api"
    session_id: str | None = None
    client_id: str | None = None
    batch_id: str | None = None
    access_profile_id: str | None = None
    external_system_id: str | None = None
    run_start_strategy: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    result_summary: str | None = None
    operational_summary: str | None = None
    technical_summary: str | None = None
    result_payload: dict[str, Any] | None = None
    ai_summary_used: bool = False
    summary_source: Literal["ai", "deterministic"] | None = None
    summary_reason: str | None = None
    error_message: str | None = None


class ActionRunResponse(BaseModel):
    status: str = "ok"
    run: RunRecord


class RunsListResponse(BaseModel):
    status: str = "ok"
    count: int
    runs: list[RunRecord]


class RunDetailResponse(BaseModel):
    status: str = "ok"
    run: RunRecord
