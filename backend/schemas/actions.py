from __future__ import annotations

from typing import Any

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
    review_status: str | None = None
    review_last_run_id: str | None = None
    reviewed_overlay: dict[str, Any] = Field(default_factory=dict)
    ai_review_summary: str | None = None
    final_summary_instruction: str | None = None
    extraction_review: dict[str, Any] = Field(default_factory=dict)
    replay_hints: list[str] = Field(default_factory=list)
    waits: list[dict] = Field(default_factory=list)
    wait_strategies: list[dict] = Field(default_factory=list)
    variable_schema: list[dict] = Field(default_factory=list)
    extraction_target: str | None = None
    objective: str = ""
    input_description: str = ""
    expected_result: str = ""
    success_criteria: str = ""
    output_type: str = ""
    output_schema: dict[str, Any] = Field(default_factory=dict)
    extraction_targets: list[str] = Field(default_factory=list)
    user_result_summary_template: str | None = None
    ai_result_summary_enabled: bool = True
    ai_recovery_enabled: bool = False
    learning_warnings: list[str] = Field(default_factory=list)
    external_system_name: str | None = None
    external_login_url: str | None = None
    access_profile_name: str | None = None
    access_profile_email_or_identifier: str | None = None
    microsoft_saved_account_identifier: str | None = None
    microsoft_saved_account_selector: str | None = None
    microsoft_saved_account_text: str | None = None
    expected_system_host: str | None = None
    microsoft_hosts: list[str] = Field(default_factory=list)
    requires_authenticated_session: bool = True
    session_guardian_enabled: bool = True
    legacy_unconfigured: bool = False
    action_timeout_seconds: int | None = None
    browser_mode: str = "browserless"
    url_inicial: str | None = None
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
