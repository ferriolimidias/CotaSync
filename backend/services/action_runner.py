from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.agente import executar_acao_fast_track
from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.services.runs_repository import append_run, update_run

logger = logging.getLogger("cotasync.action_runner")

_SENSITIVE_KEYS = {
    "authorization",
    "bearer",
    "celular",
    "cnpj",
    "cookie",
    "cpf",
    "email",
    "key",
    "password",
    "phone",
    "secret",
    "senha",
    "telefone",
    "token",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def missing_required_variables(action: ActionDetail, variables: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for variable in action.variables:
        if not variable.required:
            continue
        value = variables.get(variable.key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(variable.key)
    return missing


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(part in lowered for part in _SENSITIVE_KEYS)


def _mask_scalar(value: Any, *, reveal_last: int = 4) -> str:
    text = str(value)
    if not text:
        return ""
    if len(text) <= reveal_last:
        return "*" * len(text)
    return f"{'*' * (len(text) - reveal_last)}{text[-reveal_last:]}"


def mask_variables(variables: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, value in variables.items():
        if _is_sensitive_key(key):
            masked[str(key)] = _mask_scalar(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            masked[str(key)] = value
        else:
            masked[str(key)] = "[valor estruturado omitido]"
    return masked


def _safe_result_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    for key in ("evidencia", "arquivos", "dados_extraidos"):
        value = result.get(key)
        if value:
            payload[key] = value
    return payload or None


async def run_action_sync(action: ActionDetail, request: ActionRunRequest) -> RunRecord:
    created_at = utc_now_iso()
    run = RunRecord(
        id=str(uuid4()),
        action_id=action.id,
        action_key=action.key,
        status="pending",
        mode=request.mode,
        requested_by=request.requested_by.strip() or "api",
        created_at=created_at,
        variables=mask_variables(request.variables),
    )
    append_run(run)

    run.status = "running"
    run.started_at = utc_now_iso()
    update_run(run)

    try:
        if action.steps_count <= 0:
            raise RuntimeError("Acao aprendida nao possui passos para execucao.")

        result = await executar_acao_fast_track(action.key, request.variables)
        text = str(result.get("texto") or "").strip()
        if text.startswith("❌") or "Falha" in text or "falha" in text:
            raise RuntimeError(text or "Falha na execucao da acao.")

        run.status = "success"
        run.result_summary = text or "Execucao concluida."
        run.result_payload = _safe_result_payload(result)
    except Exception as exc:
        logger.info("Run %s finalizada com erro: %s", run.id, exc)
        run.status = "error"
        run.result_summary = "Execucao finalizada com erro."
        run.error_message = str(exc)
        run.result_payload = None
    finally:
        run.finished_at = utc_now_iso()
        update_run(run)

    return run
