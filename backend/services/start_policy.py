"""Authoritative start policy for new logical CotaSync units."""

from __future__ import annotations

from typing import Any

EXTERNAL_ENTRY_EACH_RUN = "external_entry_each_run"
PERSISTENT_GRAPH_REENTRY = "persistent_graph_reentry"
VALID_START_STRATEGIES = {EXTERNAL_ENTRY_EACH_RUN, PERSISTENT_GRAPH_REENTRY}


def normalize_start_strategy(value: Any, default: str = PERSISTENT_GRAPH_REENTRY) -> str:
    strategy = str(value or default).strip()
    return strategy or default


def requires_external_entry(strategy: Any) -> bool:
    return normalize_start_strategy(strategy) == EXTERNAL_ENTRY_EACH_RUN


def needs_fresh_external_start(strategy: Any, *, same_logical_unit: bool = False) -> bool:
    """Whether this boundary must establish a fresh external cursor."""
    return requires_external_entry(strategy) and not same_logical_unit


def logical_start_phases(strategy: Any, *, same_logical_unit: bool = False) -> tuple[str, ...]:
    """Describe the phases without mixing bootstrap into the main graph."""
    if needs_fresh_external_start(strategy, same_logical_unit=same_logical_unit):
        return ("external_entry", "access_bootstrap", "main_action")
    return ("main_action",)


def resolve_external_entry_url(
    system_config: dict[str, Any] | None,
    action_config: dict[str, Any] | None = None,
) -> str:
    system = system_config if isinstance(system_config, dict) else {}
    action = action_config if isinstance(action_config, dict) else {}
    return str(
        action.get("entry_url")
        or action.get("external_login_url")
        or system.get("entry_url")
        or system.get("external_login_url")
        or ""
    ).strip()


def validate_fresh_start_context(
    *,
    strategy: Any,
    entry_url: Any,
    access_profile_id: Any,
) -> dict[str, Any]:
    """Return structured requirements for a new logical execution unit."""
    normalized = normalize_start_strategy(strategy)
    if normalized not in VALID_START_STRATEGIES:
        return {"valid": False, "code": "run_start_strategy_invalid", "run_start_strategy": normalized}
    if not requires_external_entry(normalized):
        return {"valid": True, "required": False, "run_start_strategy": normalized}
    if not str(access_profile_id or "").strip():
        return {
            "valid": False,
            "required": True,
            "code": "access_profile_required",
            "run_start_strategy": normalized,
        }
    resolved_entry = str(entry_url or "").strip()
    if not resolved_entry:
        return {
            "valid": False,
            "required": True,
            "code": "entry_url_missing",
            "run_start_strategy": normalized,
        }
    return {
        "valid": True,
        "required": True,
        "run_start_strategy": normalized,
        "entry_url": resolved_entry,
        "access_profile_id": str(access_profile_id).strip(),
    }
