"""Client HTTP minimo para o catalogo de acoes exibido no Streamlit."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests


DEFAULT_API_BASE_URL = "http://cotasync_test_backend:8000"
DEFAULT_UI_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "ui_map.json"


class ActionsCatalogError(RuntimeError):
    """Falha controlada ao obter ou normalizar o catalogo de acoes."""


class DemoApiError(RuntimeError):
    """Falha controlada no ciclo assistido da demonstracao."""


@dataclass(frozen=True)
class ActionsUiResult:
    actions: list[dict[str, Any]]
    source: Literal["api", "fallback_local"]
    api_error: str | None = None
    fallback_error: str | None = None


def _api_base_url(explicit_url: str | None = None) -> str:
    configured = explicit_url or os.getenv("COTASYNC_API_BASE_URL") or DEFAULT_API_BASE_URL
    return configured.strip().rstrip("/")


def _normalize_variable(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        key = raw.strip()
        return {"key": key, "label": key, "required": True} if key else None
    if not isinstance(raw, dict):
        return None

    key = str(raw.get("key") or raw.get("name") or raw.get("id") or "").strip()
    if not key:
        return None
    label = str(raw.get("label") or raw.get("nome") or key).strip() or key
    return {
        "key": key,
        "label": label,
        "required": bool(raw.get("required", raw.get("obrigatorio", True))),
    }


def _normalize_variables(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    variables: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        variable = _normalize_variable(item)
        if variable is None or variable["key"] in seen:
            continue
        variables.append(variable)
        seen.add(variable["key"])
    return variables


def _normalize_api_action(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    key = str(raw.get("key") or "").strip()
    if not key:
        return None
    name = str(raw.get("name") or key).strip() or key
    try:
        steps_count = max(0, int(raw.get("steps_count", 0)))
    except (TypeError, ValueError):
        steps_count = 0

    return {
        "id": str(raw.get("id") or key).strip() or key,
        "key": key,
        "name": name,
        "description": str(raw.get("description") or "").strip(),
        "variables": _normalize_variables(raw.get("variables", [])),
        "steps_count": steps_count,
        "has_url": bool(raw.get("has_url", False)),
        "test_mode": bool(raw.get("test_mode", False)),
        "execution_type": raw.get("execution_type"),
        "learning_mode": raw.get("learning_mode"),
        "ai_reviewed": bool(raw.get("ai_reviewed", False)),
        "ai_observer_summary": str(raw.get("ai_observer_summary") or "").strip(),
        "replay_hints": raw.get("replay_hints", []) if isinstance(raw.get("replay_hints"), list) else [],
        "wait_strategies": (
            raw.get("wait_strategies", []) if isinstance(raw.get("wait_strategies"), list) else []
        ),
        "source": str(raw.get("source") or "api"),
    }


def _normalize_local_action(key: str, raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    steps = data.get("passos_playwright", [])
    if not isinstance(steps, list):
        steps = []
    return {
        "id": key,
        "key": key,
        "name": str(data.get("nome_amigavel") or key).strip() or key,
        "description": str(data.get("descricao") or "").strip(),
        "variables": _normalize_variables(data.get("variaveis_necessarias", [])),
        "steps_count": len(steps),
        "has_url": bool(str(data.get("url_inicial") or data.get("url") or "").strip()),
        "test_mode": bool(data.get("modo_teste", False)),
        "execution_type": data.get("tipo_execucao"),
        "learning_mode": data.get("learning_mode"),
        "ai_reviewed": bool(data.get("ai_reviewed", False)),
        "ai_observer_summary": str(data.get("ai_observer_summary") or "").strip(),
        "replay_hints": data.get("replay_hints", []) if isinstance(data.get("replay_hints"), list) else [],
        "wait_strategies": (
            data.get("wait_strategies", []) if isinstance(data.get("wait_strategies"), list) else []
        ),
        "source": "data/ui_map.json",
    }


def get_actions_from_api(
    api_base_url: str | None = None,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """Consulta GET /api/actions e devolve apenas acoes validas normalizadas."""

    url = f"{_api_base_url(api_base_url)}/api/actions"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ActionsCatalogError("API de acoes indisponivel.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
        raise ActionsCatalogError("Resposta invalida da API de acoes.")

    actions: list[dict[str, Any]] = []
    for raw_action in payload["actions"]:
        action = _normalize_api_action(raw_action)
        if action is not None:
            actions.append(action)
    return actions


def get_actions_fallback_local(
    ui_map_path: Path | str = DEFAULT_UI_MAP_PATH,
) -> list[dict[str, Any]]:
    """Le o catalogo legado local quando a API nao estiver disponivel."""

    path = Path(ui_map_path)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else {"acoes_conhecidas": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise ActionsCatalogError("Falha ao ler o catalogo local de acoes.") from exc

    if not isinstance(payload, dict):
        raise ActionsCatalogError("Formato invalido do catalogo local de acoes.")
    raw_actions = payload.get("acoes_conhecidas", {})
    if not isinstance(raw_actions, dict):
        raise ActionsCatalogError("Formato invalido das acoes no catalogo local.")

    return [_normalize_local_action(str(key), value) for key, value in raw_actions.items()]


def get_actions_for_ui(
    api_base_url: str | None = None,
    ui_map_path: Path | str = DEFAULT_UI_MAP_PATH,
) -> ActionsUiResult:
    """Tenta a API primeiro e recorre ao arquivo local de forma controlada."""

    try:
        return ActionsUiResult(actions=get_actions_from_api(api_base_url), source="api")
    except ActionsCatalogError as api_exc:
        try:
            actions = get_actions_fallback_local(ui_map_path)
        except ActionsCatalogError as fallback_exc:
            return ActionsUiResult(
                actions=[],
                source="fallback_local",
                api_error=str(api_exc),
                fallback_error=str(fallback_exc),
            )
        return ActionsUiResult(
            actions=actions,
            source="fallback_local",
            api_error=str(api_exc),
        )


def demo_api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    api_base_url: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Executa uma chamada controlada aos endpoints da demo v0.1."""

    url = f"{_api_base_url(api_base_url)}/{str(path).lstrip('/')}"
    try:
        response = requests.request(
            method.upper(),
            url,
            json=payload,
            timeout=timeout,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not response.ok:
            detail = body.get("detail") if isinstance(body, dict) else None
            raise DemoApiError(str(detail or "Operacao da demonstracao indisponivel."))
    except DemoApiError:
        raise
    except requests.RequestException as exc:
        raise DemoApiError("API da demonstracao indisponivel.") from exc

    if not isinstance(body, dict):
        raise DemoApiError("Resposta invalida da API da demonstracao.")
    return body
