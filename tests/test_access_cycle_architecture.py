"""Architectural guards for the persisted access-cycle boundary."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _ensure_call_sites() -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for path in (ROOT / "backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ensure_access_cycle":
                result.append((str(path.relative_to(ROOT)), node.lineno))
    return result


def test_only_persisted_access_cycle_executor_calls_coordinator():
    call_sites = _ensure_call_sites()
    assert call_sites
    assert all(path == "backend/services/access_cycles.py" for path, _line in call_sites)


def test_learning_does_not_import_or_call_coordinator_directly():
    source = (ROOT / "backend/services/demo_session.py").read_text(encoding="utf-8")
    assert "ensure_access_cycle" not in source
    assert "create_access_cycle" in source
    assert "_await_learning_access_cycle" in source


def test_learning_gate_requires_terminal_access_state():
    source = (ROOT / "backend/services/demo_session.py").read_text(encoding="utf-8")
    assert 'cycle.get("status") != "ready"' in source
    assert 'cycle.get("stage") != "external_system_ready"' in source

