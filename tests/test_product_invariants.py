from __future__ import annotations

from backend.services.start_policy import (
    EXTERNAL_ENTRY_EACH_RUN,
    logical_start_phases,
    needs_fresh_external_start,
    validate_fresh_start_context,
)


def _valid_context() -> dict[str, str]:
    return {"strategy": EXTERNAL_ENTRY_EACH_RUN, "entry_url": "https://example.test/entry", "profile": "profile-a"}


def test_new_individual_fresh_start() -> None:
    context = _valid_context()
    result = validate_fresh_start_context(
        strategy=context["strategy"], entry_url=context["entry_url"], access_profile_id=context["profile"]
    )
    assert result["valid"] is True
    assert needs_fresh_external_start(context["strategy"]) is True
    assert logical_start_phases(context["strategy"]) == ("external_entry", "access_bootstrap", "main_action")


def test_batch_each_client_fresh_start() -> None:
    context = _valid_context()
    starts = [
        logical_start_phases(context["strategy"])
        for _client in ("A", "B", "C")
    ]
    assert sum("external_entry" in phases for phases in starts) == 3
    assert sum("access_bootstrap" in phases for phases in starts) == 3


def test_new_learning_fresh_start() -> None:
    context = _valid_context()
    assert needs_fresh_external_start(context["strategy"]) is True
    assert logical_start_phases(context["strategy"])[0] == "external_entry"


def test_multi_output_same_logical_unit_does_not_restart() -> None:
    context = _valid_context()
    assert needs_fresh_external_start(context["strategy"], same_logical_unit=True) is False
    assert logical_start_phases(context["strategy"], same_logical_unit=True) == ("main_action",)


def test_access_bootstrap_is_not_main_graph() -> None:
    context = _valid_context()
    phases = logical_start_phases(context["strategy"])
    assert phases.index("access_bootstrap") < phases.index("main_action")
    assert phases.count("access_bootstrap") == 1
