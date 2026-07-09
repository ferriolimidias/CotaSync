from __future__ import annotations

import csv
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from backend.services.actions_repository import project_root

CLIENT_TEMPLATE_COLUMNS = ["id", "name", "group", "active", "grupo", "cota", "versao", "notes"]

VARIABLE_ALIASES = {
    "grupo": ("grupo",),
    "cota": ("cota", "grupo_2"),
    "grupo_2": ("grupo_2", "cota"),
    "versao": ("versao", "vers_o", "grupo_3"),
    "vers_o": ("vers_o", "versao", "grupo_3"),
    "grupo_3": ("grupo_3", "versao", "vers_o"),
}


class ClientsRepositoryError(Exception):
    """Erro controlado no cadastro persistente de clientes."""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def default_clients_path() -> Path:
    return project_root() / "data" / "clients" / "clients.json"


def _empty_payload() -> dict[str, list[dict[str, Any]]]:
    return {"clients": []}


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_payload()
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else _empty_payload()
    except (json.JSONDecodeError, OSError) as exc:
        raise ClientsRepositoryError("data/clients/clients.json invalido.") from exc
    if not isinstance(payload, dict):
        raise ClientsRepositoryError("data/clients/clients.json deve conter um objeto JSON.")
    clients = payload.get("clients")
    if clients is None:
        payload["clients"] = []
    if not isinstance(payload.get("clients"), list):
        raise ClientsRepositoryError("Campo clients deve ser uma lista.")
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
        raise ClientsRepositoryError("Nao foi possivel salvar clientes.") from exc


def _parse_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().casefold()
    if not text:
        return default
    return text in {"1", "true", "sim", "s", "yes", "y", "ativo", "active"}


def _normalize_variables(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key).strip(): "" if value is None else str(value)
        for key, value in raw.items()
        if str(key).strip()
    }


def _first_variable_value(variables: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(variables.get(key, "") or "")
        if value.strip():
            return value
    return ""


def normalize_client_variables(raw_variables: Any) -> dict[str, str]:
    variables = _normalize_variables(raw_variables)
    if "cota" not in variables or not variables["cota"].strip():
        cota = _first_variable_value(variables, ("grupo_2",))
        if cota:
            variables["cota"] = cota
    if "versao" not in variables or not variables["versao"].strip():
        versao = _first_variable_value(variables, ("vers_o", "grupo_3"))
        if versao:
            variables["versao"] = versao
    return variables


def get_client_display_fields(client: dict[str, Any]) -> dict[str, str]:
    variables = normalize_client_variables(client.get("variables", {}))
    return {
        "grupo": _first_variable_value(variables, ("grupo",)),
        "cota": _first_variable_value(variables, ("cota", "grupo_2")),
        "versao": _first_variable_value(variables, ("versao", "vers_o", "grupo_3")),
    }


def resolve_variables_for_action(client: dict[str, Any], action_variable_schema: list[Any]) -> dict[str, str]:
    variables = normalize_client_variables(client.get("variables", {}))
    resolved: dict[str, str] = {}
    for variable in action_variable_schema:
        key = str(getattr(variable, "key", "") or "").strip()
        if not key and isinstance(variable, dict):
            key = str(variable.get("key") or "").strip()
        if not key:
            continue
        aliases = VARIABLE_ALIASES.get(key, (key,))
        resolved[key] = _first_variable_value(variables, aliases)
    return resolved


def _normalize_client(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    base = existing if isinstance(existing, dict) else {}
    client_id = str(raw.get("id") or base.get("id") or uuid4()).strip()
    name = str(raw.get("name") or base.get("name") or "").strip()
    if not name:
        raise ClientsRepositoryError("Nome do cliente e obrigatorio.")
    group = str(raw.get("group") or base.get("group") or "Lista Principal").strip() or "Lista Principal"
    variables = normalize_client_variables(base.get("variables", {}))
    variables.update(normalize_client_variables(raw.get("variables", {})))
    return {
        "id": client_id,
        "name": name,
        "active": _parse_bool(raw.get("active"), bool(base.get("active", True))),
        "group": group,
        "notes": str(raw.get("notes") if raw.get("notes") is not None else base.get("notes", "")).strip(),
        "created_at": str(base.get("created_at") or now),
        "updated_at": now,
        "variables": variables,
        "display_variables": {
            "grupo": _first_variable_value(variables, ("grupo",)),
            "cota": _first_variable_value(variables, ("cota", "grupo_2")),
            "versao": _first_variable_value(variables, ("versao", "vers_o", "grupo_3")),
        },
    }


def load_clients(path: Path | None = None) -> list[dict[str, Any]]:
    payload = _load_payload(path or default_clients_path())
    clients: list[dict[str, Any]] = []
    for raw in payload["clients"]:
        if isinstance(raw, dict):
            clients.append(_normalize_client(raw, raw))
    return clients


def save_clients(clients: list[dict[str, Any]], path: Path | None = None) -> None:
    _write_payload(path or default_clients_path(), {"clients": clients})


def list_clients(
    *,
    group: str | None = None,
    include_inactive: bool = True,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    clients = load_clients(path)
    if group:
        clients = [client for client in clients if str(client.get("group") or "") == group]
    if not include_inactive:
        clients = [client for client in clients if bool(client.get("active", True))]
    clients.sort(key=lambda item: (str(item.get("group") or ""), str(item.get("name") or "")))
    return clients


def get_client(client_id: str, path: Path | None = None) -> dict[str, Any] | None:
    wanted = str(client_id or "").strip()
    for client in load_clients(path):
        if str(client.get("id") or "") == wanted:
            return client
    return None


def create_client(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    clients = load_clients(path)
    client = _normalize_client(data)
    clients.append(client)
    save_clients(clients, path)
    return client


def update_client(client_id: str, data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    clients = load_clients(path)
    wanted = str(client_id or "").strip()
    for index, existing in enumerate(clients):
        if str(existing.get("id") or "") == wanted:
            clients[index] = _normalize_client({**data, "id": wanted}, existing)
            save_clients(clients, path)
            return clients[index]
    raise ClientsRepositoryError("Cliente nao encontrado.")


def deactivate_client(client_id: str, path: Path | None = None) -> dict[str, Any]:
    return update_client(client_id, {"active": False}, path)


def delete_client(client_id: str, path: Path | None = None) -> None:
    clients = load_clients(path)
    remaining = [client for client in clients if str(client.get("id") or "") != str(client_id or "").strip()]
    if len(remaining) == len(clients):
        raise ClientsRepositoryError("Cliente nao encontrado.")
    save_clients(remaining, path)


def parse_clients_csv(csv_text: str) -> list[dict[str, Any]]:
    text = str(csv_text or "")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        if raw_row is None:
            continue
        row = {
            str(key or "").lstrip("\ufeff").strip(): "" if value is None else str(value)
            for key, value in raw_row.items()
            if key is not None and str(key).strip()
        }
        if not any(value.strip() for value in row.values()):
            continue
        variables = {
            key: value
            for key, value in row.items()
            if key not in {"id", "name", "group", "active", "notes"}
        }
        if "cota" not in variables and row.get("grupo_2"):
            variables["cota"] = row["grupo_2"]
        if "versao" not in variables:
            if row.get("grupo_3"):
                variables["versao"] = row["grupo_3"]
            elif row.get("vers_o"):
                variables["versao"] = row["vers_o"]
        rows.append(
            {
                "id": row.get("id", "").strip(),
                "name": row.get("name", "").strip(),
                "group": row.get("group", "").strip() or "Lista Principal",
                "active": _parse_bool(row.get("active"), True),
                "notes": row.get("notes", "").strip(),
                "variables": variables,
            }
        )
    return rows


def import_clients_csv(csv_text: str, path: Path | None = None) -> dict[str, Any]:
    incoming = parse_clients_csv(csv_text)
    clients = load_clients(path)
    by_id = {str(client.get("id") or ""): index for index, client in enumerate(clients)}
    by_name_group = {
        (str(client.get("name") or "").casefold(), str(client.get("group") or "").casefold()): index
        for index, client in enumerate(clients)
    }
    created = 0
    updated = 0
    imported: list[dict[str, Any]] = []
    for raw in incoming:
        existing_index: int | None = None
        raw_id = str(raw.get("id") or "").strip()
        if raw_id and raw_id in by_id:
            existing_index = by_id[raw_id]
        else:
            key = (str(raw.get("name") or "").casefold(), str(raw.get("group") or "").casefold())
            existing_index = by_name_group.get(key)

        if existing_index is None:
            client = _normalize_client(raw)
            clients.append(client)
            created += 1
        else:
            client = _normalize_client(raw, clients[existing_index])
            clients[existing_index] = client
            updated += 1
        imported.append(client)
    save_clients(clients, path)
    return {"created": created, "updated": updated, "count": len(imported), "clients": imported}


def list_groups(path: Path | None = None) -> list[str]:
    groups = sorted({str(client.get("group") or "").strip() for client in load_clients(path) if str(client.get("group") or "").strip()})
    return groups


def validate_clients_for_action(
    action: Any,
    *,
    client_group: str | None = None,
    client_ids: list[str] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    required = [
        str(getattr(variable, "key", "") or "").strip()
        for variable in getattr(action, "variables", []) or []
        if bool(getattr(variable, "required", True)) and str(getattr(variable, "key", "") or "").strip()
    ]
    selected = list_clients(group=client_group, include_inactive=True, path=path)
    wanted_ids = {str(item) for item in client_ids or [] if str(item).strip()}
    if wanted_ids:
        selected = [client for client in selected if str(client.get("id") or "") in wanted_ids]

    ready: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    inactive: list[dict[str, Any]] = []
    for client in selected:
        resolved_variables = resolve_variables_for_action(client, getattr(action, "variables", []) or [])
        missing = [key for key in required if not str(resolved_variables.get(key, "")).strip()]
        summary = {
            "id": client.get("id", ""),
            "name": client.get("name", ""),
            "group": client.get("group", ""),
            "active": bool(client.get("active", True)),
            "variables": resolved_variables,
            "display_variables": get_client_display_fields(client),
            "missing_variables": missing,
        }
        if not bool(client.get("active", True)):
            inactive.append(summary)
        elif missing:
            incomplete.append(summary)
        else:
            ready.append(summary)
    return {
        "required_variables": required,
        "ready": ready,
        "incomplete": incomplete,
        "inactive": inactive,
    }


def client_template_csv() -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CLIENT_TEMPLATE_COLUMNS)
    writer.writeheader()
    writer.writerow(
        {
            "name": "Cliente 1",
            "group": "Lista Principal",
            "active": "true",
            "grupo": "935",
            "cota": "110",
            "versao": "00",
        }
    )
    return output.getvalue()
