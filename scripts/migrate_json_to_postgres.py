#!/usr/bin/env python3
"""Import legacy JSON operational data into PostgreSQL.

The legacy files are read explicitly here only. The normal application path
does not use this module as a persistence fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import (  # noqa: E402
    Action, ActionStep, ActionVersion, Batch, BatchItem, Client,
    ExtractionContract, ExternalSystem, Run, Schedule, SessionLocal, User,
)
from backend.services.auth import hash_password  # noqa: E402
from backend.services.actions_repository import slugify_action_id  # noqa: E402


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def text(value: Any) -> str:
    return "" if value is None else str(value)


def clients_source() -> list[dict[str, Any]]:
    return read_json(ROOT / "data/clients/clients.json", {"clients": []}).get("clients", [])


def actions_source() -> list[tuple[str, dict[str, Any]]]:
    raw = read_json(ROOT / "data/ui_map.json", {"acoes_conhecidas": {}}).get("acoes_conhecidas", {})
    if not isinstance(raw, dict):
        return []
    return [(str(key), value if isinstance(value, dict) else {}) for key, value in raw.items()]


def runs_source() -> list[dict[str, Any]]:
    return read_json(ROOT / "data/runs/runs.json", {"runs": []}).get("runs", [])


def batches_source() -> list[dict[str, Any]]:
    result = []
    for path in sorted((ROOT / "data/batches").glob("*.json")):
        payload = read_json(path, {})
        if isinstance(payload, dict):
            result.append(payload)
    return result


def schedules_source() -> list[dict[str, Any]]:
    result = []
    for path in sorted((ROOT / "data/agendamentos").glob("job_*.json")):
        payload = read_json(path, {})
        if isinstance(payload, dict):
            payload.setdefault("_source_file", path.name)
            result.append(payload)
    return result


def extraction_contracts(action_id: str, version_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("reviewed_overlay", {}).get("extraction", {}) if isinstance(data.get("reviewed_overlay"), dict) else {}
    review = data.get("extraction_review", {})
    targets = raw.get("targets") if isinstance(raw, dict) else None
    if not isinstance(targets, list):
        targets = review.get("targets") if isinstance(review, dict) else []
    if not isinstance(targets, list):
        targets = []
    if isinstance(raw, dict) and raw and not targets:
        targets = [raw]
    if isinstance(review, dict) and review and not targets:
        targets = [review]
    if isinstance(data.get("extraction_targets"), list):
        targets.extend({"target_name": item, "screen_label": item} for item in data["extraction_targets"] if item)
    if not targets and data.get("extraction_target"):
        targets = [{"target_name": data.get("extraction_target"), "screen_label": data.get("extraction_target")}]
    contracts = []
    seen: set[str] = set()
    for index, item in enumerate(targets):
        if isinstance(item, str):
            item = {"target_name": item, "screen_label": item}
        if not isinstance(item, dict):
            continue
        target = text(item.get("target_name") or item.get("target_label_user") or item.get("name") or item.get("target") or data.get("extraction_target") or f"target_{index+1}").strip()
        if target in seen:
            continue
        seen.add(target)
        contracts.append({
            "id": text(item.get("id") or f"{version_id}-contract-{index+1}"),
            "action_version_id": version_id,
            "target_name": target,
            "screen_label": text(item.get("screen_label") or item.get("label")),
            "selection_type": text(item.get("selection_type") or item.get("type") or "field_value"),
            "value_type": text(item.get("value_type") or item.get("value_pattern") or "string"),
            "return_format": text(item.get("return_format") or "text"),
            "selector_data": item.get("selector_data") if isinstance(item.get("selector_data"), dict) else {},
            "anchor_data": item.get("anchor_data") if isinstance(item.get("anchor_data"), dict) else {key: item.get(key) for key in ("selector_hint", "nearby_text") if item.get(key)},
            "validation_data": item.get("validation_data") if isinstance(item.get("validation_data"), dict) else {key: item.get(key) for key in ("value_pattern",) if item.get(key)},
            "example_value": text(item.get("example_value") or item.get("expected_example") or item.get("example")) or None,
            "summary_instruction": text(item.get("summary_instruction") or data.get("final_summary_instruction")) or None,
            "status": text(item.get("status") or "active"),
        })
    return contracts


def migrate(apply: bool) -> dict[str, Any]:
    sources = {
        "clients": clients_source(),
        "actions": actions_source(),
        "runs": runs_source(),
        "batches": batches_source(),
        "schedules": schedules_source(),
    }
    counts: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "source": {key: len(value) for key, value in sources.items()},
        "migrated": {},
        "errors": [],
        "skipped": [],
    }
    if not apply:
        counts["planned"] = {
            "users": 2,
            "clients": len(sources["clients"]),
            "actions": len(sources["actions"]),
            "action_versions": len(sources["actions"]),
            "action_steps": sum(len(item[1].get("robust_steps") or item[1].get("passos_playwright") or []) for item in sources["actions"]),
            "runs": len(sources["runs"]),
            "batches": len(sources["batches"]),
            "batch_items": sum(len(item.get("rows", [])) for item in sources["batches"]),
            "schedules": len(sources["schedules"]),
            "extraction_contracts": sum(len(extraction_contracts(action_id, f"{action_id}-v1", raw)) for _, raw in sources["actions"] for action_id in [slugify_action_id(text(raw.get("nome_amigavel") or raw.get("name") or _))]),
        }
        return counts

    with SessionLocal.begin() as session:
        configured = []
        for role in ("admin", "operator"):
            username = os.getenv(f"COTASYNC_{role.upper()}_USERNAME", role).strip()
            password_hash = os.getenv(f"COTASYNC_{role.upper()}_PASSWORD_HASH", "").strip()
            password = os.getenv(f"COTASYNC_{role.upper()}_PASSWORD", "").strip()
            if username and not password_hash and password:
                password_hash = hash_password(password)
            if username and password_hash:
                configured.append((username, role, password_hash))
        for username, role, password_hash in configured:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                session.add(User(id=str(uuid4()), username=username, role=role, password_hash=password_hash, active=True))
            else:
                user.role, user.password_hash = role, password_hash
        action_ids: dict[str, str] = {}
        version_ids: dict[str, str] = {}
        for raw in sources["clients"]:
            if not isinstance(raw, dict) or not raw.get("id"):
                counts["skipped"].append({"resource": "clients", "reason": "invalid row"})
                continue
            variables = raw.get("variables") if isinstance(raw.get("variables"), dict) else {}
            client = session.get(Client, text(raw["id"]))
            if client is None:
                client = Client(id=text(raw["id"]), name=text(raw.get("name")), client_group=text(raw.get("group") or raw.get("client_group") or "Lista Principal"), active=bool(raw.get("active", True)), variables=variables, notes=text(raw.get("notes")))
                session.add(client)
            client.name = text(raw.get("name"))
            client.client_group = text(raw.get("group") or raw.get("client_group") or "Lista Principal")
            client.active = bool(raw.get("active", True))
            client.variables = variables
            client.grupo = text(variables.get("grupo")) or None
            client.cota = text(variables.get("cota") or variables.get("grupo_2")) or None
            client.versao = text(variables.get("versao") or variables.get("vers_o") or variables.get("grupo_3")) or None
            client.notes = text(raw.get("notes"))
            client.created_at = dt(raw.get("created_at")) or client.created_at
            client.updated_at = dt(raw.get("updated_at")) or client.updated_at
        extraction_count = 0
        for key, raw in sources["actions"]:
            action_id = slugify_action_id(text(raw.get("nome_amigavel") or raw.get("name") or key))
            action_ids[key] = action_id
            action = session.get(Action, action_id)
            if action is None:
                action = Action(id=action_id, key=key, name=text(raw.get("nome_amigavel") or raw.get("name") or key), description=text(raw.get("descricao") or raw.get("description")), status="published")
                session.add(action)
                session.flush()
            version_id = f"{action_id}-v1"
            version_ids[key] = version_id
            version = session.get(ActionVersion, version_id)
            definition = raw
            variables = {"schema": raw.get("variable_schema") or raw.get("variaveis_necessarias") or []}
            if version is None:
                version = ActionVersion(id=version_id, action_id=action_id, version_number=1, status="published", definition=definition, variables=variables, metadata_json={"legacy_key": key}, created_at=dt(raw.get("created_at")) or datetime.now(UTC), published_at=datetime.now(UTC))
                session.add(version)
            else:
                version.definition, version.variables = definition, variables
            session.flush()
            steps = raw.get("robust_steps") or raw.get("passos_playwright") or []
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    step = {"raw": step}
                step_id = f"{version_id}-step-{index}"
                db_step = session.get(ActionStep, step_id)
                if db_step is None:
                    db_step = ActionStep(id=step_id, action_version_id=version_id, step_index=index, step_type=text(step.get("tipo") or step.get("type") or "unknown"), selector=text(step.get("seletor") or step.get("selector")) or None, variable_key=text(step.get("variavel") or step.get("variable")) or None, step_data=step)
                    session.add(db_step)
            for contract in extraction_contracts(action_id, version_id, raw):
                existing = session.get(ExtractionContract, contract["id"])
                if existing is None:
                    session.add(ExtractionContract(**contract))
                else:
                    for field, value in contract.items():
                        if field != "id":
                            setattr(existing, field, value)
                extraction_count += 1
            session.flush()
            action.published_version_id = version_id
        session.flush()
        action_by_key = {key: action_ids[key] for key in action_ids}
        for raw in sources["runs"]:
            run_id = text(raw.get("id"))
            if not run_id:
                continue
            run = session.get(Run, run_id)
            payload = raw.get("result_payload") if isinstance(raw.get("result_payload"), dict) else {}
            action_key = text(raw.get("action_key") or raw.get("action_id"))
            action_id = action_by_key.get(action_key)
            action_version_id = version_ids.get(action_key)
            if run is None:
                run = Run(id=run_id, action_id=action_id, action_version_id=action_version_id, status=text(raw.get("status") or "unknown"), runner=text(payload.get("runner") or raw.get("runner")) or None, started_at=dt(raw.get("started_at")), finished_at=dt(raw.get("finished_at")), result_summary=text(raw.get("result_summary") or raw.get("operational_summary")) or None, extracted_data=payload.get("dados_extraidos") if isinstance(payload.get("dados_extraidos"), dict) else {}, input_variables=raw.get("variables") if isinstance(raw.get("variables"), dict) else {}, diagnostics={"raw": raw.get("technical_summary"), "payload": payload.get("diagnostics")}, step_trace=payload.get("step_trace") if isinstance(payload.get("step_trace"), list) else [], error_data={"message": raw.get("error_message")} if raw.get("error_message") else {}, screenshot_path=payload.get("screenshot_path"))
                session.add(run)
        for raw in sources["batches"]:
            batch_id = text(raw.get("batch_id") or raw.get("id"))
            if not batch_id:
                continue
            key = text(raw.get("action_key") or raw.get("action_id"))
            batch = session.get(Batch, batch_id)
            if batch is None:
                rows = raw.get("rows") if isinstance(raw.get("rows"), list) else []
                batch = Batch(id=batch_id, action_id=action_by_key.get(key) or text(raw.get("action_id")) or None, action_version_id=version_ids.get(key), client_group=text(raw.get("client_group")) or None, status=text(raw.get("status") or "unknown"), delay_seconds=float(raw.get("delay_between_rows_seconds") or 0), total_items=len(rows), processed_items=sum(1 for row in rows if isinstance(row, dict) and text(row.get("status")).lower() in {"success", "completed"}), created_by=text(raw.get("requested_by")) or None, created_at=dt(raw.get("created_at")) or datetime.now(UTC), started_at=dt(raw.get("started_at")), finished_at=dt(raw.get("finished_at")), metadata_json={"source": raw.get("source")})
                session.add(batch)
                session.flush()
                for position, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    item_id = f"{batch_id}-item-{position}"
                    if session.get(BatchItem, item_id) is None:
                        session.add(BatchItem(id=item_id, batch_id=batch_id, client_id=text(row.get("client_id")) or None, position=position, status=text(row.get("status") or "unknown"), run_id=text(row.get("run_id")) or None, input_variables=row.get("variables") if isinstance(row.get("variables"), dict) else {}, result_data=row.get("result_payload") if isinstance(row.get("result_payload"), dict) else {}, error_data={"message": row.get("error_message")} if row.get("error_message") else {}, started_at=dt(row.get("started_at")), finished_at=dt(row.get("finished_at"))))
        ext = read_json(ROOT / "data/external_systems/current.json", {})
        if isinstance(ext, dict) and ext:
            existing = session.scalar(select(ExternalSystem).where(ExternalSystem.name == text(ext.get("external_system_name") or "default")))
            if existing is None:
                session.add(ExternalSystem(id=str(uuid4()), name=text(ext.get("external_system_name") or "default"), config=ext))
        for raw in sources["schedules"]:
            schedule_id = text(raw.get("id") or raw.get("job_id") or raw.get("_source_file"))
            if not schedule_id:
                continue
            key = text(raw.get("action_key") or raw.get("action_id"))
            schedule = session.get(Schedule, schedule_id)
            if schedule is None:
                schedule = Schedule(id=schedule_id, name=text(raw.get("name") or raw.get("nome") or schedule_id), action_id=action_by_key.get(key), client_group=text(raw.get("client_group") or raw.get("grupo_clientes")) or None, frequency=text(raw.get("frequency") or raw.get("frequencia") or "legacy"), timezone=text(raw.get("timezone") or "America/Sao_Paulo"), schedule_config=raw, delay_seconds=float(raw.get("delay_seconds") or raw.get("delay_between_rows_seconds") or 0), active=bool(raw.get("active", raw.get("ativo", False))), next_run_at=dt(raw.get("next_run_at")), last_run_at=dt(raw.get("last_run_at")), created_by=text(raw.get("created_by") or raw.get("requested_by")) or None, created_at=dt(raw.get("created_at")) or datetime.now(UTC))
                session.add(schedule)
    counts["migrated"] = {"users": len(configured), "clients": len(sources["clients"]), "actions": len(sources["actions"]), "action_versions": len(sources["actions"]), "action_steps": sum(len(raw.get("robust_steps") or raw.get("passos_playwright") or []) for _, raw in sources["actions"]), "runs": len(sources["runs"]), "batches": len(sources["batches"]), "batch_items": sum(len(item.get("rows", [])) for item in sources["batches"]), "schedules": len(sources["schedules"]), "extraction_contracts": extraction_count}
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.apply), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
