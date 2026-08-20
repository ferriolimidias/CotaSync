from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from backend.schemas.runs import RunRecord, RunStatus
from backend.db import Run as DbRun, SessionLocal

logger = logging.getLogger("cotasync.runs")

def _parse_dt(value: str | None):
    if not value:
        return None
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed
    except ValueError:
        return None


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


def _use_legacy_json(path: Path | None) -> bool:
    return path is not None or os.getenv("COTASYNC_TEST_LEGACY_JSON", "").strip().lower() in {"1", "true", "yes"}


def load_runs(path: Path | None = None) -> list[RunRecord]:
    if not _use_legacy_json(path):
        with SessionLocal() as session:
            rows = session.query(DbRun).order_by(DbRun.created_at).all()
            result = []
            for row in rows:
                record = (row.diagnostics or {}).get("_record", {}) if isinstance(row.diagnostics, dict) else {}
                payload = (row.diagnostics or {}).get("_result_payload", {}) if isinstance(row.diagnostics, dict) else {}
                record = dict(record) if isinstance(record, dict) else {}
                record.update({
                    "id": row.id,
                    "action_id": row.action_id or record.get("action_id") or "",
                    "action_key": record.get("action_key") or row.action_id or "",
                    "status": row.status if row.status in {"pending", "running", "success", "error"} else "error",
                    "created_at": row.created_at.isoformat() if row.created_at else record.get("created_at") or "",
                    "started_at": row.started_at.isoformat() if row.started_at else record.get("started_at"),
                    "finished_at": row.finished_at.isoformat() if row.finished_at else record.get("finished_at"),
                    "variables": row.input_variables or record.get("variables") or {},
                    "result_summary": row.result_summary or record.get("result_summary"),
                    "result_payload": payload or record.get("result_payload"),
                })
                result.append(RunRecord.model_validate(record))
            return result
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
    if not _use_legacy_json(path):
        with SessionLocal.begin() as session:
            for run in runs:
                raw = run.model_dump()
                row = session.get(DbRun, run.id)
                if row is None:
                    row = DbRun(id=run.id, status=run.status)
                    session.add(row)
                from backend.db import Action as DbAction
                row.action_id = run.action_id if session.get(DbAction, run.action_id) is not None else None
                row.status = run.status
                row.started_at = _parse_dt(run.started_at)
                row.finished_at = _parse_dt(run.finished_at)
                row.result_summary = run.result_summary or run.operational_summary
                row.input_variables = run.variables
                row.extracted_data = (run.result_payload or {}).get("dados_extraidos", {})
                row.step_trace = (run.result_payload or {}).get("step_trace", [])
                row.screenshot_path = (run.result_payload or {}).get("screenshot_path")
                row.diagnostics = {"_record": raw, "_result_payload": run.result_payload or {}, "technical_summary": run.technical_summary}
        return
    runs_path = path or default_runs_path()
    payload = {"runs": [run.model_dump() for run in runs]}
    _write_payload(runs_path, payload)


def append_run(run: RunRecord, path: Path | None = None) -> RunRecord:
    if not _use_legacy_json(path):
        save_runs([run], None)
        return run
    runs = load_runs(path)
    runs.append(run)
    save_runs(runs, path)
    return run


def update_run(run: RunRecord, path: Path | None = None) -> RunRecord:
    if not _use_legacy_json(path):
        save_runs([run], None)
        return run
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
    if not _use_legacy_json(path):
        with SessionLocal() as session:
            row = session.get(DbRun, str(run_id or "").strip())
            if row is None:
                return None
        return next((item for item in load_runs(None) if item.id == str(run_id or "").strip()), None)
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
