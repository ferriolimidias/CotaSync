"""Authoritative start policy for new logical CotaSync units."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EXTERNAL_ENTRY_EACH_RUN = "external_entry_each_run"
PERSISTENT_GRAPH_REENTRY = "persistent_graph_reentry"
VALID_START_STRATEGIES = {EXTERNAL_ENTRY_EACH_RUN, PERSISTENT_GRAPH_REENTRY}


def normalize_external_entry_url(value: Any) -> str:
    """Repair one known legacy serialization defect without changing authority.

    Older configuration writes could serialize the first OAuth parameter as
    ``https://host/path?client_id=<value>`` inside the query string.  The
    configured host, path and parameter values remain authoritative; this only
    restores the lost parameter name when the embedded URL exactly matches the
    enclosing URL and carries one empty parameter value.
    """
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.query:
        return raw
    repaired: list[tuple[str, str]] = []
    changed = False
    for key, parameter_value in parse_qsl(parsed.query, keep_blank_values=True):
        embedded = urlsplit(key)
        embedded_pairs = parse_qsl(embedded.query, keep_blank_values=True)
        if not embedded_pairs and embedded.query and "=" not in embedded.query and "&" not in embedded.query:
            embedded_pairs = [(embedded.query, "")]
        same_entry = (
            embedded.scheme == parsed.scheme
            and embedded.netloc == parsed.netloc
            and embedded.path == parsed.path
            and len(embedded_pairs) == 1
            and embedded_pairs[0][1] == ""
        )
        if same_entry:
            repaired.append((embedded_pairs[0][0], parameter_value))
            changed = True
        else:
            repaired.append((key, parameter_value))
    if not changed:
        return raw
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(repaired), parsed.fragment))


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
    del action_config
    system = system_config if isinstance(system_config, dict) else {}
    # New logical units must use the configured system entry. Legacy login
    # metadata and action definitions are not navigation authorities.
    return normalize_external_entry_url(system.get("entry_url"))


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
