from __future__ import annotations

from typing import Any


def normalize_outputs(action: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapts legacy singular extraction metadata without changing published actions."""
    outputs = action.get("outputs")
    if isinstance(outputs, list):
        return [dict(item) for item in outputs if isinstance(item, dict)]
    contract = action.get("extraction_review")
    if isinstance(contract, dict) and contract:
        return [{"output_id": "output_1", "type": "data", **dict(contract)}]
    return []


def output_from_contract(contract: dict[str, Any], *, output_id: str, destination: dict[str, Any] | None = None) -> dict[str, Any]:
    selector_data = contract.get("selector_data") if isinstance(contract.get("selector_data"), dict) else {}
    selector = str(selector_data.get("primary") or contract.get("selector_hint") or "").strip()
    return {
        "output_id": output_id,
        "label": str(contract.get("target_name") or contract.get("screen_label") or output_id),
        "type": "data",
        "selector": selector,
        "preferred_selector": selector,
        "fallback_selectors": list(selector_data.get("candidates") or []),
        "page_ref": str(contract.get("page_ref") or ""),
        "state_id": str(contract.get("state_id") or ""),
        "read_mode": str(contract.get("read_mode") or "text"),
        "normalization": contract.get("normalization") or "exact_text",
        "example_value": str(contract.get("example_value") or ""),
        "destination": destination,
        "contract": dict(contract),
    }
