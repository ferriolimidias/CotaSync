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
