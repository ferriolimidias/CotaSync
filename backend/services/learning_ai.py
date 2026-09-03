from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.services.learning_trace import sanitize_trace


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


class LearningAIObserver:
    def __init__(self, provider: LearningAIProvider | None = None) -> None:
        self.enabled = os.getenv("AI_ENABLED", "false").lower() in {"1", "true", "yes"}
        self.provider = provider or DisabledLearningAIProvider()

    def analyze(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        safe_trace = sanitize_trace(trace)
        if not self.enabled:
            return DisabledLearningAIProvider().analyze(safe_trace)
        return sanitize_trace(self.provider.analyze(safe_trace))


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
