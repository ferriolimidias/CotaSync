"""Structured, secret-safe execution timeline events."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit


_SENSITIVE_KEY = re.compile(r"(?:token|secret|password|senha|cookie|authorization|oauth|client_secret)", re.I)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_LOG = logging.getLogger("cotasync.run_timeline")
_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "operation.log"


def sanitize_url(value: Any) -> str:
    try:
        parsed = urlsplit(str(value or ""))
        if not parsed.hostname:
            return ""
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path or "/", "", ""))
    except Exception:
        return ""


def mask_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * max(1, len(text) - 4)}{text[-4:]}"


def _safe_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if key in {"url", "entry_url", "current_url", "next_url"}:
        return sanitize_url(value)
    if key in {"selector", "target_text", "login_identifier"}:
        return _EMAIL.sub("[IDENTIFIER]", str(value))[:500]
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), item) for k, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"[{type(value).__name__}]"


def _ensure_file_handler() -> None:
    if any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == _LOG_FILE for handler in _LOG.handlers):
        return
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        _LOG.addHandler(handler)
        _LOG.setLevel(logging.INFO)
        _LOG.propagate = False
    except OSError:
        # Container stdout remains the fallback structured log sink.
        pass


class RunTimeline:
    """Emit ordered run events without changing execution control flow."""

    def __init__(self, *, run_id: str, context: dict[str, Any] | None = None, heartbeat_seconds: float = 10.0) -> None:
        self.run_id = str(run_id)
        self.context = dict(context or {})
        self.heartbeat_seconds = heartbeat_seconds
        self._last_waiting_at = 0.0

    def emit(self, stage: str, event: str, status: str, **details: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "stage": str(stage),
            "event": str(event),
            "status": str(status),
            **self.context,
        }
        payload.update({key: _safe_value(str(key), value) for key, value in details.items() if value is not None})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        _ensure_file_handler()
        _LOG.info("RUN_TIMELINE %s", encoded)
        return payload

    def waiting(self, target: str, **details: Any) -> None:
        now = time.monotonic()
        if self._last_waiting_at and now - self._last_waiting_at < self.heartbeat_seconds:
            return
        self._last_waiting_at = now
        self.emit("runtime_wait", "WAITING_EXTERNAL_SYSTEM", "active", wait_target=target, **details)


TimelineCallback = Callable[..., Any]
