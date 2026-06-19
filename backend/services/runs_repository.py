from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from backend.schemas.runs import RunRecord, RunStatus

logger = logging.getLogger("cotasync.runs")


class RunsRepositoryError(Exception):
    """Erro seguro de leitura ou escrita do arquivo temporario de runs."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_runs_path() -> Path:
    return project_root() / "data" / "runs" / "runs.json"


def _empty_payload() -> dict[str, list[dict[str, Any]]]:
    return {"runs": []}


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_payload()

    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else _empty_payload()
    except json.JSONDecodeError as exc:
        logger.exception("JSON invalido em data/runs/runs.json: %s", exc)
        raise RunsRepositoryError("data/runs/runs.json invalido.") from exc
    except OSError as exc:
        logger.exception("Falha ao ler data/runs/runs.json: %s", exc)
        raise RunsRepositoryError("Nao foi possivel ler data/runs/runs.json.") from exc

    if not isinstance(payload, dict):
        raise RunsRepositoryError("data/runs/runs.json deve conter um objeto JSON.")
    if payload.get("runs") is None:
        payload["runs"] = []
    if not isinstance(payload.get("runs"), list):
        raise RunsRepositoryError("Campo runs deve ser uma lista.")
    return payload


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.exception("Falha ao gravar data/runs/runs.json: %s", exc)
        raise RunsRepositoryError("Nao foi possivel gravar data/runs/runs.json.") from exc


def load_runs(path: Path | None = None) -> list[RunRecord]:
    runs_path = path or default_runs_path()
    payload = _load_payload(runs_path)
    runs: list[RunRecord] = []
    for raw_run in payload["runs"]:
        if not isinstance(raw_run, dict):
            logger.warning("Run ignorada por formato invalido em data/runs/runs.json.")
            continue
        runs.append(RunRecord(**raw_run))
    return runs


def save_runs(runs: list[RunRecord], path: Path | None = None) -> None:
    runs_path = path or default_runs_path()
    payload = {"runs": [run.model_dump() for run in runs]}
    _write_payload(runs_path, payload)


def append_run(run: RunRecord, path: Path | None = None) -> RunRecord:
    runs = load_runs(path)
    runs.append(run)
    save_runs(runs, path)
    return run


def update_run(run: RunRecord, path: Path | None = None) -> RunRecord:
    runs = load_runs(path)
    for index, existing in enumerate(runs):
        if existing.id == run.id:
            runs[index] = run
            save_runs(runs, path)
            return run
    runs.append(run)
    save_runs(runs, path)
    return run


def get_run(run_id: str, path: Path | None = None) -> RunRecord | None:
    wanted = str(run_id or "").strip()
    for run in load_runs(path):
        if run.id == wanted:
            return run
    return None


def list_runs(
    *,
    action_id: str | None = None,
    status: RunStatus | None = None,
    limit: int | None = None,
    path: Path | None = None,
) -> list[RunRecord]:
    runs = load_runs(path)
    if action_id:
        wanted = str(action_id).strip()
        runs = [run for run in runs if run.action_id == wanted or run.action_key == wanted]
    if status:
        runs = [run for run in runs if run.status == status]

    runs.sort(key=lambda run: run.started_at or run.created_at, reverse=True)
    if limit is not None:
        safe_limit = max(0, min(int(limit), 500))
        runs = runs[:safe_limit]
    return runs
