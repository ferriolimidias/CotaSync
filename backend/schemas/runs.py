from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["pending", "running", "success", "error"]
RunMode = Literal["sync", "async"]


class ActionRunRequest(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)
    mode: RunMode = "sync"
    requested_by: str = "api"
    session_id: str | None = None


class RunRecord(BaseModel):
    id: str
    action_id: str
    action_key: str
    status: RunStatus
    mode: RunMode = "sync"
    run_type: str = "action_run"
    requested_by: str = "api"
    session_id: str | None = None
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
