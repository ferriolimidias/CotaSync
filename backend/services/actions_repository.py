from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.schemas.actions import ActionDetail, ActionStepPreview, ActionSummary, ActionVariable
from backend.services.external_systems import DEFAULT_ACCESS_PROFILE, load_current_external_system

logger = logging.getLogger("cotasync.actions")

SOURCE_LABEL = "data/ui_map.json"


class ActionsRepositoryError(Exception):
    """Erro seguro de leitura/parsing do catalogo de acoes."""


@dataclass(frozen=True)
class ActionsCatalog:
    actions: list[ActionDetail]
    exists: bool
    warning: str | None = None


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_ui_map_path() -> Path:
    return project_root() / "data" / "ui_map.json"


def slugify_action_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_value.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "acao"


def _normalize_variable(raw: Any) -> ActionVariable | None:
    if isinstance(raw, str):
        key = raw.strip()
        if not key:
            return None
        return ActionVariable(key=key, label=key, required=True)

    if isinstance(raw, dict):
        key = str(raw.get("key") or raw.get("name") or raw.get("id") or "").strip()
        if not key:
            return None
        label = str(raw.get("label") or raw.get("nome") or key).strip() or key
        required_raw = raw.get("required", raw.get("obrigatorio", True))
        return ActionVariable(key=key, label=label, required=bool(required_raw))

    return None


def _normalize_variables(raw_variables: Any) -> list[ActionVariable]:
    if not isinstance(raw_variables, list):
        return []

    variables: list[ActionVariable] = []
    seen: set[str] = set()
    for raw in raw_variables:
        variable = _normalize_variable(raw)
        if variable is None or variable.key in seen:
            continue
        variables.append(variable)
        seen.add(variable.key)
    return variables


def _friendly_variables(data: dict[str, Any]) -> list[ActionVariable]:
    variables = _normalize_variables(data.get("variaveis_necessarias", []))
    schema_variables = _normalize_variables(data.get("variable_schema", []))
    if not variables:
        return schema_variables
    labels_by_key = {item.key: item.label for item in schema_variables if item.label}
    return [
        variable.model_copy(update={"label": labels_by_key.get(variable.key, variable.label)})
        for variable in variables
    ]


def _steps_preview(raw_steps: Any, limit: int = 10) -> list[ActionStepPreview]:
    if not isinstance(raw_steps, list):
        return []

    preview: list[ActionStepPreview] = []
    for index, raw_step in enumerate(raw_steps[:limit], start=1):
        if not isinstance(raw_step, dict):
            preview.append(
                ActionStepPreview(index=index, type="desconhecido", has_selector=False, has_variable=False)
            )
            continue
        step_type = str(raw_step.get("tipo") or raw_step.get("type") or "desconhecido").strip() or "desconhecido"
        preview.append(
            ActionStepPreview(
                index=index,
                type=step_type,
                has_selector=bool(str(raw_step.get("seletor") or raw_step.get("selector") or "").strip()),
                has_variable=bool(str(raw_step.get("variavel") or raw_step.get("variable") or "").strip()),
            )
        )
    return preview


def _unique_action_id(base_id: str, used_ids: set[str]) -> str:
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _extraction_targets(data: dict[str, Any], raw_steps: Any) -> list[str]:
    configured = data.get("extraction_targets")
    if isinstance(configured, list):
        targets = [str(item).strip() for item in configured if str(item).strip()]
        if targets:
            return targets
    if not isinstance(raw_steps, list):
        return []
    targets: list[str] = []
    for step in raw_steps:
        if not isinstance(step, dict) or str(step.get("tipo") or "").strip().lower() != "extrair_texto":
            continue
        target = str(step.get("nome") or "").strip()
        if target and target not in targets:
            targets.append(target)
    return targets


def _default_access_profile() -> dict[str, Any]:
    try:
        return load_current_external_system()
    except Exception:
        return dict(DEFAULT_ACCESS_PROFILE)


def action_has_access_profile(data: dict[str, Any]) -> bool:
    return bool(
        str(data.get("access_profile_name") or "").strip()
        and (
            str(data.get("microsoft_saved_account_identifier") or "").strip()
            or str(data.get("access_profile_email_or_identifier") or "").strip()
        )
        and str(data.get("microsoft_saved_account_text") or "").strip()
        and str(data.get("expected_system_host") or "").strip()
    )


def enrich_action_access_profile(data: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(data)
    profile = _default_access_profile()
    identifier = str(
        enriched.get("microsoft_saved_account_identifier")
        or enriched.get("access_profile_email_or_identifier")
        or profile.get("microsoft_saved_account_identifier")
        or profile.get("access_profile_email_or_identifier")
        or ""
    ).strip()
    defaults = {
        "access_profile_name": profile.get("access_profile_name") or DEFAULT_ACCESS_PROFILE["access_profile_name"],
        "access_profile_email_or_identifier": identifier,
        "microsoft_saved_account_identifier": identifier,
        "microsoft_saved_account_selector": profile.get("microsoft_saved_account_selector") or "",
        "microsoft_saved_account_text": (
            profile.get("microsoft_saved_account_text")
            or DEFAULT_ACCESS_PROFILE["microsoft_saved_account_text"]
        ),
        "expected_system_host": profile.get("expected_system_host") or DEFAULT_ACCESS_PROFILE["expected_system_host"],
        "microsoft_hosts": profile.get("microsoft_hosts") or DEFAULT_ACCESS_PROFILE["microsoft_hosts"],
        "requires_authenticated_session": True,
        "session_guardian_enabled": True,
    }
    for key, value in defaults.items():
        if key in {"requires_authenticated_session", "session_guardian_enabled"}:
            enriched[key] = bool(enriched.get(key, value))
        elif key == "microsoft_hosts":
            raw_hosts = enriched.get(key)
            enriched[key] = raw_hosts if isinstance(raw_hosts, list) and raw_hosts else list(value)
        elif not str(enriched.get(key) or "").strip():
            enriched[key] = value
    return enriched


def _normalize_action(key: str, raw_action: Any, used_ids: set[str]) -> ActionDetail:
    data = raw_action if isinstance(raw_action, dict) else {}
    has_profile_metadata = action_has_access_profile(data)
    normalized_profile = enrich_action_access_profile(data)
    name = str(data.get("nome_amigavel") or data.get("name") or key).strip() or key
    description = str(data.get("descricao") or data.get("description") or "").strip()
    raw_steps = data.get("passos_playwright", [])
    steps_count = len(raw_steps) if isinstance(raw_steps, list) else 0
    action_id = _unique_action_id(slugify_action_id(name or key), used_ids)
    execution_type_raw = data.get("tipo_execucao")
    execution_type = str(execution_type_raw).strip() if execution_type_raw is not None else None
    extraction_targets = _extraction_targets(data, raw_steps)
    learning_mode = str(data.get("learning_mode") or "").strip()
    mechanically_learned = learning_mode in {
        "human_demo_mechanical_ai_reviewed",
        "desktop_browser_mechanical_ai_reviewed",
    }

    summary = ActionSummary(
        id=action_id,
        key=key,
        name=name,
        description=description,
        variables=_friendly_variables(data),
        steps_count=steps_count,
        has_url=bool(str(data.get("url_inicial") or data.get("url") or "").strip()),
        test_mode=bool(data.get("modo_teste", False)),
        execution_type=execution_type or None,
        learning_mode=learning_mode or None,
        ai_reviewed=bool(data.get("ai_reviewed", False)),
        ai_observer_summary=str(data.get("ai_observer_summary") or "").strip() or None,
        replay_hints=data.get("replay_hints", []) if isinstance(data.get("replay_hints"), list) else [],
        waits=data.get("waits", []) if isinstance(data.get("waits"), list) else [],
        wait_strategies=(
            data.get("wait_strategies", []) if isinstance(data.get("wait_strategies"), list) else []
        ),
        variable_schema=data.get("variable_schema", []) if isinstance(data.get("variable_schema"), list) else [],
        extraction_target=str(data.get("extraction_target") or "").strip() or None,
        objective=str(data.get("objective") or description or name).strip(),
        input_description=str(data.get("input_description") or "").strip(),
        expected_result=str(data.get("expected_result") or "").strip(),
        success_criteria=str(data.get("success_criteria") or "").strip(),
        output_type=str(data.get("output_type") or "").strip(),
        output_schema=data.get("output_schema", {}) if isinstance(data.get("output_schema"), dict) else {},
        extraction_targets=extraction_targets,
        user_result_summary_template=str(data.get("user_result_summary_template") or "").strip() or None,
        ai_result_summary_enabled=bool(data.get("ai_result_summary_enabled", True)),
        ai_recovery_enabled=bool(data.get("ai_recovery_enabled", False)),
        learning_warnings=(
            data.get("learning_warnings", []) if isinstance(data.get("learning_warnings"), list) else []
        ),
        external_system_name=str(data.get("external_system_name") or "").strip() or None,
        external_login_url=str(data.get("external_login_url") or "").strip() or None,
        access_profile_name=str(normalized_profile.get("access_profile_name") or "").strip() or None,
        access_profile_email_or_identifier=str(
            normalized_profile.get("access_profile_email_or_identifier") or ""
        ).strip() or None,
        microsoft_saved_account_identifier=str(
            normalized_profile.get("microsoft_saved_account_identifier") or ""
        ).strip() or None,
        microsoft_saved_account_selector=str(
            normalized_profile.get("microsoft_saved_account_selector") or ""
        ).strip() or None,
        microsoft_saved_account_text=str(
            normalized_profile.get("microsoft_saved_account_text") or ""
        ).strip() or None,
        expected_system_host=str(normalized_profile.get("expected_system_host") or "").strip() or None,
        microsoft_hosts=(
            normalized_profile.get("microsoft_hosts")
            if isinstance(normalized_profile.get("microsoft_hosts"), list)
            else []
        ),
        requires_authenticated_session=bool(normalized_profile.get("requires_authenticated_session", True)),
        session_guardian_enabled=bool(normalized_profile.get("session_guardian_enabled", True)),
        legacy_unconfigured=not (has_profile_metadata or (mechanically_learned and steps_count > 0)),
        action_timeout_seconds=(
            int(data["action_timeout_seconds"])
            if str(data.get("action_timeout_seconds") or "").strip().isdigit()
            else None
        ),
        browser_mode=str(data.get("browser_mode") or "browserless").strip() or "browserless",
        url_inicial=str(data.get("url_inicial") or data.get("url") or "").strip() or None,
        source=SOURCE_LABEL,
    )
    return ActionDetail(**summary.model_dump(), steps_preview=_steps_preview(raw_steps))


def _load_ui_map(path: Path) -> tuple[dict[str, Any], bool, str | None]:
    if not path.is_file():
        logger.info("ui_map nao encontrado em %s; retornando catalogo vazio.", path)
        return {"acoes_conhecidas": {}}, False, "data/ui_map.json nao encontrado; catalogo vazio."

    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else {"acoes_conhecidas": {}}
    except json.JSONDecodeError as exc:
        logger.exception("JSON invalido em data/ui_map.json: %s", exc)
        raise ActionsRepositoryError("data/ui_map.json invalido.") from exc
    except OSError as exc:
        logger.exception("Falha ao ler data/ui_map.json: %s", exc)
        raise ActionsRepositoryError("Nao foi possivel ler data/ui_map.json.") from exc

    if not isinstance(payload, dict):
        raise ActionsRepositoryError("data/ui_map.json deve conter um objeto JSON.")
    return payload, True, None


def load_actions_catalog(path: Path | None = None) -> ActionsCatalog:
    ui_map_path = path or default_ui_map_path()
    payload, exists, warning = _load_ui_map(ui_map_path)
    raw_actions = payload.get("acoes_conhecidas", {})
    if raw_actions is None:
        raw_actions = {}
    if not isinstance(raw_actions, dict):
        raise ActionsRepositoryError("Campo acoes_conhecidas deve ser um objeto.")

    used_ids: set[str] = set()
    actions = [
        _normalize_action(str(key), raw_action, used_ids)
        for key, raw_action in raw_actions.items()
    ]
    logger.info("Catalogo de acoes carregado: %s acoes encontradas.", len(actions))
    return ActionsCatalog(actions=actions, exists=exists, warning=warning)


def find_action(action_id: str, path: Path | None = None) -> ActionDetail | None:
    wanted = str(action_id or "").strip()
    wanted_slug = slugify_action_id(wanted)
    catalog = load_actions_catalog(path)

    for action in catalog.actions:
        candidates = {
            action.id,
            action.key,
            slugify_action_id(action.key),
            action.name,
            slugify_action_id(action.name),
        }
        if wanted in candidates or wanted_slug in candidates:
            return action
    return None
