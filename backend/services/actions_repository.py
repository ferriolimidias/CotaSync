from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from backend.schemas.actions import ActionDetail, ActionStepPreview, ActionSummary, ActionVariable
from backend.db import (
    Action as DbAction,
    ActionStep,
    ActionVersion,
    Batch as DbBatch,
    BatchItem,
    ExtractionContract,
    Run as DbRun,
    Schedule,
    SessionLocal,
)
from backend.services.action_pages import url_host
from backend.services.client_fields import canonical_client_field_key, client_field_label
from backend.services.external_systems import DEFAULT_ACCESS_PROFILE, load_current_external_system

logger = logging.getLogger("cotasync.actions")

SOURCE_LABEL = "data/ui_map.json"
_MICROSOFT_HOST_SUFFIXES = (
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "login.windows.net",
    "m365.cloud.microsoft",
)


class ActionsRepositoryError(Exception):
    """Erro seguro de leitura/parsing do catalogo de acoes."""


class ActionDeletionError(ActionsRepositoryError):
    """Impedimento de negocio para excluir ou arquivar uma acao."""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


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
        canonical = canonical_client_field_key(key)
        if canonical:
            return ActionVariable(key=canonical, label=client_field_label(canonical), required=True, source="client")
        return ActionVariable(key=key, label=key, required=True, source="runtime")

    if isinstance(raw, dict):
        key = str(raw.get("key") or raw.get("name") or raw.get("id") or "").strip()
        if not key:
            return None
        canonical = canonical_client_field_key(key)
        if canonical:
            key = canonical
        label = client_field_label(key) if canonical else str(raw.get("label") or raw.get("nome") or key).strip() or key
        required_raw = raw.get("required", raw.get("obrigatorio", True))
        source = "client" if canonical else str(raw.get("source") or "runtime").strip() or "runtime"
        return ActionVariable(key=key, label=label, required=bool(required_raw), source=source)

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
        and _clean_expected_system_host(data.get("expected_system_host"))
    )


def _clean_expected_system_host(value: Any) -> str:
    host = url_host(value) or str(value or "").strip().lower().rstrip(".")
    if not host or "/" in host or "?" in host:
        return ""
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in _MICROSOFT_HOST_SUFFIXES):
        return ""
    return host


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
        "access_profile_name": profile.get("access_profile_name") or DEFAULT_ACCESS_PROFILE.get("access_profile_name", ""),
        "access_profile_email_or_identifier": identifier,
        "microsoft_saved_account_identifier": identifier,
        "microsoft_saved_account_selector": profile.get("microsoft_saved_account_selector") or "",
        "microsoft_saved_account_text": (
            profile.get("microsoft_saved_account_text")
            or DEFAULT_ACCESS_PROFILE.get("microsoft_saved_account_text", "")
        ),
        "expected_system_host": _clean_expected_system_host(profile.get("expected_system_host"))
        or DEFAULT_ACCESS_PROFILE.get("expected_system_host", ""),
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
        elif key == "expected_system_host":
            enriched[key] = _clean_expected_system_host(enriched.get(key)) or value
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
        review_status=str(data.get("review_status") or "").strip() or None,
        review_last_run_id=str(data.get("review_last_run_id") or "").strip() or None,
        reviewed_overlay=data.get("reviewed_overlay", {}) if isinstance(data.get("reviewed_overlay"), dict) else {},
        ai_review_summary=str(data.get("ai_review_summary") or "").strip() or None,
        final_summary_instruction=str(data.get("final_summary_instruction") or "").strip() or None,
        extraction_review=data.get("extraction_review", {}) if isinstance(data.get("extraction_review"), dict) else {},
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
        outputs=data.get("outputs", []) if isinstance(data.get("outputs"), list) else [],
        output_states=data.get("output_states", []) if isinstance(data.get("output_states"), list) else [],
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
        browser_mode=str(data.get("browser_mode") or "desktop_browser").strip() or "desktop_browser",
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
    if path is None:
        with SessionLocal() as session:
            rows = session.query(DbAction, ActionVersion).join(
                ActionVersion, ActionVersion.id == DbAction.published_version_id
            ).filter(DbAction.status != "archived").order_by(DbAction.name).all()
            actions: list[ActionDetail] = []
            used_ids: set[str] = set()
            for db_action, version in rows:
                raw = dict(version.definition or {})
                raw.setdefault("nome_amigavel", db_action.name)
                raw.setdefault("descricao", db_action.description)
                actions.append(_normalize_action(db_action.key, raw, used_ids))
            return ActionsCatalog(actions=actions, exists=True, warning=None)
    payload, exists, warning = _load_ui_map(path)
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


def delete_or_archive_action(action_id: str) -> dict[str, str]:
    """Exclui a definicao da acao sem remover historico operacional terminal."""
    wanted = str(action_id or "").strip()
    with SessionLocal.begin() as session:
        action = session.get(DbAction, wanted)
        if action is None:
            raise ActionDeletionError("ACTION_NOT_FOUND", "Acao nao encontrada.", 404)
        active_run = session.query(DbRun.id).filter(
            DbRun.action_id == action.id,
            DbRun.status.in_(["queued", "pending", "running"]),
        ).first()
        if active_run:
            raise ActionDeletionError(
                "ACTION_RUN_ACTIVE",
                "Esta acao possui uma execucao em andamento e nao pode ser excluida agora.",
            )

        active_batch = session.query(DbBatch.id).filter(
            DbBatch.action_id == action.id,
            DbBatch.status.in_(["queued", "running", "cancel_requested", "pending"]),
        ).first()
        if active_batch:
            raise ActionDeletionError(
                "ACTION_BATCH_ACTIVE",
                "Esta acao possui um lote em andamento e nao pode ser excluida agora.",
            )

        active_schedule = session.query(Schedule.id).filter(
            Schedule.action_id == action.id,
            Schedule.active.is_(True),
        ).first()
        if active_schedule:
            raise ActionDeletionError(
                "ACTION_SCHEDULE_ACTIVE",
                "Esta acao possui um agendamento ativo. Desative-o antes de excluir a acao.",
            )

        version_ids = [row[0] for row in session.query(ActionVersion.id).filter(ActionVersion.action_id == action.id).all()]
        if version_ids:
            action.published_version_id = None
            session.flush()
            session.execute(delete(ActionStep).where(ActionStep.action_version_id.in_(version_ids)))
            session.execute(delete(ExtractionContract).where(ExtractionContract.action_version_id.in_(version_ids)))
            session.execute(delete(ActionVersion).where(ActionVersion.id.in_(version_ids)))
        session.delete(action)
        return {"status": "deleted", "action_id": action.id}


def _action_contracts_from_payload(action_id: str, version_id: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    overlay = data.get("reviewed_overlay") if isinstance(data.get("reviewed_overlay"), dict) else {}
    review = data.get("extraction_review") if isinstance(data.get("extraction_review"), dict) else {}
    target_values: list[dict[str, Any]] = []
    outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
    for output in outputs:
        if isinstance(output, dict) and isinstance(output.get("contract"), dict):
            target_values.append({**output["contract"], "destination": output.get("destination")})
    for source in (overlay.get("extraction") if isinstance(overlay, dict) else None, review):
        if isinstance(source, dict) and source:
            target_values.append(source)
    if isinstance(data.get("extraction_targets"), list):
        target_values.extend({"target_name": item, "screen_label": item} for item in data["extraction_targets"] if item)
    if not target_values and data.get("extraction_target"):
        target_values = [{"target_name": data.get("extraction_target"), "screen_label": data.get("extraction_target")}]
    contracts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(target_values):
        if isinstance(item, str):
            item = {"target_name": item, "screen_label": item}
        if not isinstance(item, dict):
            continue
        target_name = str(
            item.get("target_name")
            or item.get("target_label_user")
            or item.get("name")
            or item.get("target")
            or data.get("extraction_target")
            or f"target_{index + 1}"
        ).strip()
        if not target_name or target_name in seen:
            continue
        seen.add(target_name)
        contracts.append(
            {
                "id": str(item.get("id") or f"{version_id}-contract-{index + 1}"),
                "action_version_id": version_id,
                "target_name": target_name,
                "screen_label": str(item.get("screen_label") or item.get("label") or ""),
                "selection_type": str(item.get("selection_type") or item.get("type") or "field_value"),
                "value_type": str(item.get("value_type") or item.get("value_pattern") or "string"),
                "return_format": str(item.get("return_format") or "text"),
                "selector_data": item.get("selector_data") if isinstance(item.get("selector_data"), dict) else {},
                "anchor_data": item.get("anchor_data") if isinstance(item.get("anchor_data"), dict) else {},
                "validation_data": item.get("validation_data") if isinstance(item.get("validation_data"), dict) else {},
                "example_value": str(item.get("example_value") or item.get("expected_example") or item.get("example") or "") or None,
                "summary_instruction": str(item.get("summary_instruction") or data.get("final_summary_instruction") or "") or None,
                "status": str(item.get("status") or "active"),
            }
        )
    return contracts


def save_learned_action(action_key: str, learned_action: dict[str, Any]) -> ActionDetail:
    action_name = str(learned_action.get("nome_amigavel") or learned_action.get("name") or action_key).strip() or action_key
    action_id = slugify_action_id(action_name)
    steps = learned_action.get("robust_steps") or learned_action.get("passos_playwright") or []
    if not isinstance(steps, list):
        steps = []
    variables = learned_action.get("variable_schema") or learned_action.get("variaveis_necessarias") or []
    if not isinstance(variables, list):
        variables = []

    with SessionLocal.begin() as session:
        action = session.scalar(select(DbAction).where(DbAction.key == action_key)) or session.get(DbAction, action_id)
        if action is None:
            action = DbAction(
                id=action_id,
                key=action_key,
                name=action_name,
                description=str(learned_action.get("descricao") or learned_action.get("description") or "").strip(),
                status="published",
            )
            session.add(action)
        else:
            if action.status == "archived":
                raise ActionsRepositoryError("Acao arquivada nao pode receber nova versao.")
            action.name = action_name
            action.description = str(learned_action.get("descricao") or learned_action.get("description") or action.description)
            action.status = str(learned_action.get("status") or action.status or "published")

        version_id = f"{action.id}-v1"
        version = session.get(ActionVersion, version_id)
        definition = dict(learned_action)
        version_variables = {"schema": variables}
        if version is None:
            version = ActionVersion(
                id=version_id,
                action_id=action.id,
                version_number=1,
                status="published",
                created_by=str(learned_action.get("created_by") or "" ) or None,
                source_version_id=None,
                definition=definition,
                variables=version_variables,
                metadata_json={"source": "learning"},
                created_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
            )
            session.add(version)
        else:
            version.definition = definition
            version.variables = version_variables
            version.status = "published"
            version.published_at = datetime.now(UTC)

        session.flush()
        session.execute(delete(ActionStep).where(ActionStep.action_version_id == version.id))
        session.execute(delete(ExtractionContract).where(ExtractionContract.action_version_id == version.id))
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                step = {"raw": step}
            session.add(
                ActionStep(
                    id=f"{version.id}-step-{index}",
                    action_version_id=version.id,
                    step_index=index,
                    step_type=str(step.get("tipo") or step.get("type") or "unknown"),
                    selector=str(step.get("seletor") or step.get("selector") or "") or None,
                    variable_key=str(step.get("variavel") or step.get("variable") or "") or None,
                    step_data=step,
                )
            )
        for contract in _action_contracts_from_payload(action.id, version.id, learned_action):
            session.add(ExtractionContract(**contract))
        session.flush()
        action.published_version_id = version.id
        session.flush()

    saved = find_action(action_id)
    if saved is not None:
        return saved
    return ActionDetail(
        id=action_id,
        key=action_key,
        name=action_name,
        description=str(learned_action.get("descricao") or ""),
        variables=[],
        steps_count=len(steps),
        has_url=bool(str(learned_action.get("url_inicial") or "").strip()),
        test_mode=False,
        execution_type=None,
        learning_mode=str(learned_action.get("learning_mode") or "") or None,
        ai_reviewed=bool(learned_action.get("ai_reviewed", False)),
        ai_observer_summary=str(learned_action.get("ai_observer_summary") or "") or None,
        review_status=str(learned_action.get("review_status") or "") or None,
        review_last_run_id=str(learned_action.get("review_last_run_id") or "") or None,
        reviewed_overlay=learned_action.get("reviewed_overlay") if isinstance(learned_action.get("reviewed_overlay"), dict) else {},
        ai_review_summary=str(learned_action.get("ai_review_summary") or "") or None,
        final_summary_instruction=str(learned_action.get("final_summary_instruction") or "") or None,
        extraction_review=learned_action.get("extraction_review") if isinstance(learned_action.get("extraction_review"), dict) else {},
        replay_hints=learned_action.get("replay_hints") if isinstance(learned_action.get("replay_hints"), list) else [],
        waits=learned_action.get("waits") if isinstance(learned_action.get("waits"), list) else [],
        wait_strategies=learned_action.get("wait_strategies") if isinstance(learned_action.get("wait_strategies"), list) else [],
        variable_schema=variables,
        extraction_target=str(learned_action.get("extraction_target") or "") or None,
        objective=str(learned_action.get("objective") or action_name),
        input_description=str(learned_action.get("input_description") or ""),
        expected_result=str(learned_action.get("expected_result") or ""),
        success_criteria=str(learned_action.get("success_criteria") or ""),
        output_type=str(learned_action.get("output_type") or ""),
        output_schema=learned_action.get("output_schema") if isinstance(learned_action.get("output_schema"), dict) else {},
        extraction_targets=[str(item) for item in learned_action.get("extraction_targets") or [] if str(item).strip()],
        user_result_summary_template=str(learned_action.get("user_result_summary_template") or "") or None,
        ai_result_summary_enabled=bool(learned_action.get("ai_result_summary_enabled", True)),
        ai_recovery_enabled=bool(learned_action.get("ai_recovery_enabled", False)),
        learning_warnings=learned_action.get("learning_warnings") if isinstance(learned_action.get("learning_warnings"), list) else [],
        external_system_name=str(learned_action.get("external_system_name") or "") or None,
        external_login_url=str(learned_action.get("external_login_url") or "") or None,
        access_profile_name=str(learned_action.get("access_profile_name") or "") or None,
        access_profile_email_or_identifier=str(learned_action.get("access_profile_email_or_identifier") or "") or None,
        microsoft_saved_account_identifier=str(learned_action.get("microsoft_saved_account_identifier") or "") or None,
        microsoft_saved_account_selector=str(learned_action.get("microsoft_saved_account_selector") or "") or None,
        microsoft_saved_account_text=str(learned_action.get("microsoft_saved_account_text") or "") or None,
        expected_system_host=str(learned_action.get("expected_system_host") or "") or None,
        microsoft_hosts=learned_action.get("microsoft_hosts") if isinstance(learned_action.get("microsoft_hosts"), list) else [],
        requires_authenticated_session=bool(learned_action.get("requires_authenticated_session", True)),
        session_guardian_enabled=bool(learned_action.get("session_guardian_enabled", True)),
        legacy_unconfigured=False,
        action_timeout_seconds=(int(learned_action["action_timeout_seconds"]) if str(learned_action.get("action_timeout_seconds") or "").strip().isdigit() else None),
        browser_mode=str(learned_action.get("browser_mode") or "desktop_browser"),
        url_inicial=str(learned_action.get("url_inicial") or "") or None,
        source=SOURCE_LABEL,
        steps_preview=_steps_preview(steps),
    )
