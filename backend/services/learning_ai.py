from __future__ import annotations

import os
import json
import logging
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from backend.services.learning_trace import sanitize_trace

logger = logging.getLogger("cotasync.learning_ai")
PROMPT_VERSION = 1


class SelectorSuggestion(BaseModel):
    selector: str
    rationale: str = ""
    confidence: float | None = None


class LearningAIAnalysis(BaseModel):
    selector_analysis: list[dict[str, Any]] = Field(default_factory=list)
    transition_analysis: list[dict[str, Any]] = Field(default_factory=list)
    output_analysis: list[dict[str, Any]] = Field(default_factory=list)
    state_analysis: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)


SYSTEM_PROMPT = """You are the CotaSync learning compiler. Prompt version 1.
The browser recorder already identified TARGET_NODE; never locate targets from images.
Analyze only sanitized evidence. Propose deterministic selectors, preconditions,
postconditions, state/output metadata and warnings. Do not invent business logic,
change client bindings, handle credentials, or suggest AI during replay.
Return only JSON matching LearningAIAnalysis. Suggestions remain untrusted until
the deterministic browser validator proves them."""


@dataclass
class LearningQualityReport:
    score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    validated_selectors: list[str] = field(default_factory=list)
    validated_postconditions: list[dict[str, Any]] = field(default_factory=list)
    outputs_validated: int = 0
    states_ambiguous: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)


class LearningAIProvider(Protocol):
    def analyze(self, trace: list[dict[str, Any]]) -> dict[str, Any]: ...


class DisabledLearningAIProvider:
    def analyze(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        return {"enabled": False, "suggestions": [], "reason": "AI_DISABLED"}


class UnavailableLearningAIProvider:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def analyze(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        return {"enabled": False, "suggestions": [], "reason": self.reason, "warnings": [self.reason]}


class OpenAICompatibleLearningProvider:
    """Small provider client kept inside learning services, never replay services."""

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def analyze(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"prompt_version": PROMPT_VERSION, "trace": trace}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        req = urlrequest.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            parsed = LearningAIAnalysis.model_validate(json.loads(content))
            return {"enabled": True, "provider": "openai_compatible", "model": self.model, **parsed.model_dump()}
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Learning AI unavailable or invalid response: %s", type(exc).__name__)
            return {"enabled": True, "provider": "openai_compatible", "model": self.model, "warnings": ["AI_UNAVAILABLE_OR_INVALID_RESPONSE"], "quality": {"blocking_issues": []}}


def configured_learning_ai_provider() -> LearningAIProvider:
    from backend.services.ai_settings import effective_settings

    settings = effective_settings()
    provider_name = settings.provider
    if provider_name not in {"openai", "openai_compatible"}:
        return UnavailableLearningAIProvider("AI_PROVIDER_UNSUPPORTED")
    api_key = settings.api_key
    if not api_key:
        return DisabledLearningAIProvider()
    return OpenAICompatibleLearningProvider(
        api_key=api_key,
        model=settings.model,
        base_url=settings.base_url,
    )


class LearningAIObserver:
    def __init__(self, provider: LearningAIProvider | None = None) -> None:
        from backend.services.ai_settings import effective_settings

        self.enabled = effective_settings().enabled
        self.provider = provider or (configured_learning_ai_provider() if self.enabled else DisabledLearningAIProvider())

    def analyze(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        safe_trace = sanitize_trace(trace)
        if not self.enabled:
            return DisabledLearningAIProvider().analyze(safe_trace)
        try:
            return sanitize_trace(self.provider.analyze(safe_trace))
        except Exception as exc:
            logger.warning("Learning AI provider failed: %s", type(exc).__name__)
            return UnavailableLearningAIProvider("AI_PROVIDER_UNAVAILABLE").analyze(safe_trace)


def validate_selector_candidate(*, candidate: dict[str, Any], captured_node_id: str, resolved_node_ids: list[str]) -> bool:
    return bool(candidate.get("selector")) and len(resolved_node_ids) == 1 and resolved_node_ids[0] == captured_node_id


def validate_postcondition_candidate(*, candidate: dict[str, Any], before_selectors: set[str], after_selectors: set[str]) -> bool:
    selector = str(candidate.get("selector") or "").strip()
    return candidate.get("kind") == "selector_present" and bool(selector) and selector not in before_selectors and selector in after_selectors


def compile_validated_learning_metadata(
    captured: dict[str, Any],
    *,
    selector_candidates: list[dict[str, Any]] | None = None,
    postcondition_candidates: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], LearningQualityReport]:
    """Compiles only deterministic evidence; AI suggestions are never trusted directly."""
    compiled = sanitize_trace(captured)
    report = LearningQualityReport(score=1.0)
    original = str(captured.get("selector") or "")
    if original:
        report.validated_selectors.append(original)
    for candidate in selector_candidates or []:
        if candidate.get("validated") is True and candidate.get("selector"):
            compiled.setdefault("fallback_selectors", []).append(str(candidate["selector"]))
            report.validated_selectors.append(str(candidate["selector"]))
    before = set(captured.get("before_selectors") or [])
    after = set(captured.get("after_selectors") or [])
    for candidate in postcondition_candidates or []:
        if validate_postcondition_candidate(candidate=candidate, before_selectors=before, after_selectors=after):
            report.validated_postconditions.append(dict(candidate))
    return compiled, report
