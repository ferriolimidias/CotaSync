from __future__ import annotations

from pydantic import BaseModel, Field


class ActionVariable(BaseModel):
    key: str
    label: str
    required: bool = True


class ActionSummary(BaseModel):
    id: str
    key: str
    name: str
    description: str
    variables: list[ActionVariable] = Field(default_factory=list)
    steps_count: int
    has_url: bool
    test_mode: bool = False
    execution_type: str | None = None
    learning_mode: str | None = None
    ai_reviewed: bool = False
    ai_observer_summary: str | None = None
    replay_hints: list[str] = Field(default_factory=list)
    waits: list[dict] = Field(default_factory=list)
    wait_strategies: list[dict] = Field(default_factory=list)
    variable_schema: list[dict] = Field(default_factory=list)
    extraction_target: str | None = None
    external_system_name: str | None = None
    external_login_url: str | None = None
    source: str = "data/ui_map.json"


class ActionStepPreview(BaseModel):
    index: int
    type: str
    has_selector: bool
    has_variable: bool


class ActionDetail(ActionSummary):
    steps_preview: list[ActionStepPreview] = Field(default_factory=list)


class ActionsListResponse(BaseModel):
    status: str = "ok"
    count: int
    actions: list[ActionSummary]
    warning: str | None = None


class ActionDetailResponse(BaseModel):
    status: str = "ok"
    action: ActionDetail


class ActionsRawResponse(BaseModel):
    status: str = "ok"
    source: str = "data/ui_map.json"
    exists: bool
    count: int
    keys: list[str] = Field(default_factory=list)
    warning: str | None = None
