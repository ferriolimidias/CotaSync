#!/usr/bin/env python3
"""Reset safe dos dados aprendidos descartaveis da demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UI_MAP_PATH = ROOT / "data" / "ui_map.json"
RUNS_PATH = ROOT / "data" / "runs" / "runs.json"
KEEP_PATHS = (
    ROOT / "data" / "external_systems" / "current.json",
    ROOT / "data" / "external_systems" / "sessions",
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def reset_demo_catalog(*, apply: bool = False) -> dict[str, Any]:
    removed: dict[str, Any] = {
        "ui_map_actions": 0,
        "runs": 0,
        "kept": [str(path.relative_to(ROOT)) for path in KEEP_PATHS],
        "applied": apply,
    }

    if UI_MAP_PATH.is_file():
        try:
            payload = json.loads(UI_MAP_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"acoes_conhecidas": {}}
        actions = payload.get("acoes_conhecidas", {}) if isinstance(payload, dict) else {}
        removed["ui_map_actions"] = len(actions) if isinstance(actions, dict) else 0
    if RUNS_PATH.is_file():
        try:
            runs_payload = json.loads(RUNS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runs_payload = {"runs": []}
        runs = runs_payload.get("runs", []) if isinstance(runs_payload, dict) else []
        removed["runs"] = len(runs) if isinstance(runs, list) else 0

    if apply:
        _write_json(UI_MAP_PATH, {"acoes_conhecidas": {}})
        _write_json(RUNS_PATH, {"runs": []})

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpa catalogo aprendido e runs descartaveis da demo.")
    parser.add_argument("--apply", action="store_true", help="Executa a limpeza. Sem isso, faz apenas dry-run.")
    args = parser.parse_args()
    result = reset_demo_catalog(apply=bool(args.apply))
    mode = "APLICADO" if result["applied"] else "DRY-RUN"
    print(f"[{mode}] Acoes aprendidas removidas: {result['ui_map_actions']}")
    print(f"[{mode}] Runs removidas: {result['runs']}")
    print("[MANTIDO] Configuracao externa, perfil de acesso e sessoes/browser profile.")
    for path in result["kept"]:
        print(f"[MANTIDO] {path}")
    if not result["applied"]:
        print("Use: python3 scripts/reset_demo_catalog.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
