from __future__ import annotations

import re
from typing import Any

SENSITIVE = re.compile(r"password|senha|token|cookie|authorization|secret|credential|mfa", re.I)


def sanitize_trace(value: Any, *, key: str = "") -> Any:
    if SENSITIVE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): sanitize_trace(v, key=str(k)) for k, v in value.items() if not SENSITIVE.search(str(k)) or str(v) == "[REDACTED]"}
    if isinstance(value, list):
        return [sanitize_trace(item, key=key) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def observation_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = ("url", "path", "host", "title", "selectors", "stable_interactive_selectors", "page_ref")
    diff: dict[str, Any] = {}
    for key in keys:
        left, right = before.get(key), after.get(key)
        if left != right:
            diff[key] = {"before": left, "after": right}
    return diff


def build_raw_learning_trace(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, event in enumerate(events):
        clean = sanitize_trace(dict(event))
        clean["event_id"] = str(clean.get("event_id") or f"event_{index + 1}")
        clean["before_after_diff"] = observation_diff(
            clean.get("page_signature_before") if isinstance(clean.get("page_signature_before"), dict) else {},
            clean.get("page_signature_after") if isinstance(clean.get("page_signature_after"), dict) else {},
        )
        result.append(clean)
    return result
