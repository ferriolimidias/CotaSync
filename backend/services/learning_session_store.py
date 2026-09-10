"""Durable storage for human learning sessions.

The browser handles remain process-local; the learning evidence and
publication state do not. This module deliberately stores only sanitized
learning metadata and never credentials or browser session material.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from sqlalchemy import select

from backend.db import LearningSession, SessionLocal

_SENSITIVE_KEY_PARTS = (
    "password",
    "senha",
    "otp",
    "mfa",
    "cookie",
    "token",
    "authorization",
    "bearer",
    "oauth",
    "private_key",
    "client_secret",
)


def sanitize_learning_value(value: Any, key: str = "") -> Any:
    lowered = str(key or "").casefold()
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        result = {str(name): sanitize_learning_value(item, str(name)) for name, item in value.items()}
        field_metadata = value.get("field_metadata")
        if isinstance(field_metadata, dict):
            field_type = str(field_metadata.get("type") or "").casefold()
            autocomplete = str(field_metadata.get("autocomplete") or "").casefold()
            if field_type == "password" or "one-time" in autocomplete or "otp" in autocomplete:
                for sensitive_name in ("value", "valor", "example_value", "text", "selected_text"):
                    if sensitive_name in result:
                        result[sensitive_name] = "[REDACTED]"
        return result
    if isinstance(value, list):
        return [sanitize_learning_value(item, key) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _now() -> datetime:
    return datetime.now(UTC)


def _optional_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def learning_evidence_fingerprint(session: Any, extra: Any = None) -> str:
    """Stable identity for the evidence reviewed by Learning AI.

    Publication status and diagnostics are deliberately excluded. A retry of
    the same stopped learning must reuse its review, while a changed step,
    binding, bootstrap or output must invalidate it.
    """
    payload = {
        "guided_learning": sanitize_learning_value(getattr(session, "guided_learning", {}) or {}),
        "raw_events": sanitize_learning_value(getattr(session, "learning_events", []) or []),
        "recorded_steps": sanitize_learning_value(getattr(session, "steps", []) or []),
        "outputs": sanitize_learning_value(getattr(session, "outputs", []) or []),
        "extraction_review": sanitize_learning_value(getattr(session, "extraction_review", {}) or {}),
        "bootstrap": sanitize_learning_value({
            "external_system_id": getattr(session, "external_system_id", ""),
            "access_profile_id": getattr(session, "access_profile_id", ""),
            "run_start_strategy": (getattr(session, "guided_learning", {}) or {}).get("run_start_strategy", ""),
        }),
        "extra": sanitize_learning_value(extra),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def session_snapshot(session: Any) -> dict[str, Any]:
    steps = [sanitize_learning_value(item) for item in getattr(session, "steps", []) if isinstance(item, dict)]
    events = [sanitize_learning_value(item) for item in getattr(session, "learning_events", []) if isinstance(item, dict)]
    variables = sorted(
        {
            str(item.get("variable_key") or item.get("variavel") or "").strip()
            for item in [*steps, *events]
            if isinstance(item, dict) and str(item.get("variable_key") or item.get("variavel") or "").strip()
        }
    )
    states: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in steps:
        for state_id, signature in (
            (step.get("before_state_id"), step.get("page_signature_before")),
            (step.get("after_state_id"), step.get("page_signature_after")),
        ):
            state_key = str(state_id or "")
            if not state_key or state_key in seen:
                continue
            seen.add(state_key)
            states.append({"state_id": state_key, "signature": signature if isinstance(signature, dict) else {}})
    guided = sanitize_learning_value(getattr(session, "guided_learning", {}) or {})
    return {
        "action_name": str((guided or {}).get("name") or ""),
        "objective": str((guided or {}).get("objective") or ""),
        "expected_result": str((guided or {}).get("expected_result") or ""),
        "status": str(getattr(session, "status", "active") or "active"),
        "recording_status": "recording" if bool(getattr(session, "recording", False)) else "stopped",
        "publication_status": str(getattr(session, "publication_status", "not_attempted") or "not_attempted"),
        "external_system_id": _optional_id(getattr(session, "external_system_id", None)),
        "access_profile_id": _optional_id(
            (guided or {}).get("required_access_profile_id") or getattr(session, "access_profile_id", None)
        ),
        "access_cycle_id": _optional_id(getattr(session, "access_cycle_id", None)),
        "allowed_list_ids": sanitize_learning_value((guided or {}).get("allowed_list_ids") or []),
        "run_start_strategy": str((guided or {}).get("run_start_strategy") or "persistent_graph_reentry"),
        "raw_events": events,
        "recorded_steps": steps,
        "bootstrap_metadata": sanitize_learning_value({
            "required_access_profile_id": (guided or {}).get("required_access_profile_id"),
            "run_start_strategy": (guided or {}).get("run_start_strategy"),
            "guided_learning": guided,
            "external_system_name": getattr(session, "external_system_name", ""),
            "external_login_url": getattr(session, "external_login_url", ""),
            "access_profile_name": getattr(session, "access_profile_name", ""),
            "access_profile_email_or_identifier": getattr(session, "access_profile_email_or_identifier", ""),
            "expected_system_host": getattr(session, "expected_system_host", ""),
        }),
        "state_evidence": states,
        "variable_bindings": variables,
        "outputs": sanitize_learning_value(getattr(session, "outputs", []) or []),
        "diagnostics": sanitize_learning_value({
            "recorder_errors": getattr(session, "recorder_errors", []) or [],
            "result_selection": getattr(session, "result_selection", {}) or {},
            "extraction_review": getattr(session, "extraction_review", {}) or {},
            "final_page_snapshot": getattr(session, "final_page_snapshot", {}) or {},
            "ai_review": getattr(session, "ai_review", {}) or {},
        }),
    }


def persist_learning_session(session: Any, *, publication: dict[str, Any] | None = None) -> int:
    snapshot = session_snapshot(session)
    if publication:
        snapshot["publication_status"] = str(publication.get("status") or snapshot["publication_status"])
        snapshot["diagnostics"] = {
            **snapshot["diagnostics"],
            "publication": sanitize_learning_value(publication),
        }
    session_id = str(session.id)
    tenant_id = str(getattr(session, "tenant_id", "default") or "default")
    with SessionLocal.begin() as db:
        row = db.scalar(select(LearningSession).where(LearningSession.id == session_id, LearningSession.tenant_id == tenant_id).with_for_update())
        if row is None:
            row = LearningSession(id=session_id, tenant_id=tenant_id)
            db.add(row)
            db.flush()
        row.revision = int(row.revision or 0) + 1
        for field in (
            "action_name", "objective", "expected_result", "status", "recording_status", "publication_status",
            "external_system_id", "access_profile_id", "allowed_list_ids", "run_start_strategy", "raw_events",
            "access_cycle_id",
            "recorded_steps", "bootstrap_metadata", "state_evidence", "variable_bindings", "outputs", "diagnostics",
        ):
            if field in snapshot:
                setattr(row, field, snapshot[field])
        if publication:
            row.publication_error_code = str(publication.get("error_code") or "") or None
            row.publication_error_stage = str(publication.get("stage") or "") or None
            row.publication_error_message = str(publication.get("message") or "")[:1000] or None
            row.published_action_id = str(publication.get("action_id") or "") or row.published_action_id
            row.published_action_version_id = str(publication.get("action_version_id") or "") or row.published_action_version_id
            if publication.get("status") == "published":
                row.published_at = _now()
        if snapshot["recording_status"] == "recording" and row.recording_started_at is None:
            row.recording_started_at = _now()
        if snapshot["recording_status"] == "stopped":
            row.recording_stopped_at = row.recording_stopped_at or _now()
        return int(row.revision)


def load_learning_session(session_id: str, tenant_id: str = "default") -> LearningSession | None:
    with SessionLocal() as db:
        return db.scalar(select(LearningSession).where(LearningSession.id == str(session_id), LearningSession.tenant_id == tenant_id))
