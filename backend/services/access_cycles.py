"""Durable orchestration for a new external-access logical unit."""

from __future__ import annotations

import logging
import asyncio
from contextvars import ContextVar
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from playwright.async_api import async_playwright

from backend.db import AccessCycle, ExternalAccessProfile, ExternalSystem, SessionLocal
from backend.services.access_coordinator import AccessCycleError, IdentityEvidenceResult, _body_text, _identity_evidence, start_canonical_access
from backend.services.access_profiles import active_access_profile_public
from backend.services.browser_providers import BrowserIdentitySession, BrowserProviderError, browser_provider, desktop_cdp_url, browser_page_identity, _desktop_version
from backend.services.session_guardian import classify_microsoft_auth_state
from backend.services.action_pages import url_host
from backend.services.start_policy import normalize_external_entry_url

logger = logging.getLogger("cotasync.access_cycles")

_WORKER_ACCESS_EXECUTOR: ContextVar[Any | None] = ContextVar("worker_access_executor", default=None)
# The worker owns live Playwright connections. Disconnecting a context created
# with new_context destroys its live pages, even if storage_state was saved.
_LIVE_PROFILE_SESSIONS: dict[str, tuple[Any, BrowserIdentitySession]] = {}


async def release_unavailable_profile_sessions(*, shutdown: bool = False) -> None:
    if not _LIVE_PROFILE_SESSIONS:
        return
    with SessionLocal() as db:
        active = set(db.scalars(select(ExternalAccessProfile.id).where(ExternalAccessProfile.active.is_(True))).all())
    for profile_id in list(_LIVE_PROFILE_SESSIONS):
        if shutdown or profile_id not in active:
            playwright, _identity = _LIVE_PROFILE_SESSIONS.pop(profile_id)
            await playwright.stop()


def bind_worker_access_executor(executor: Any) -> Any:
    return _WORKER_ACCESS_EXECUTOR.set(executor)


def reset_worker_access_executor(token: Any) -> None:
    _WORKER_ACCESS_EXECUTOR.reset(token)


def _safe_url(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _event_payload(stage: str, event: str, status: str, context: dict[str, Any]) -> dict[str, Any]:
    safe = dict(context)
    for key in ("entry_url", "url", "current_url", "path"):
        if key in safe:
            safe[key] = _safe_url(safe[key])
    for key in ("token", "cookie", "password", "secret"):
        safe.pop(key, None)
    return {"timestamp": datetime.now(UTC).isoformat(), "stage": stage, "event": event, "status": status, **safe}


def _append_event(cycle_id: str, stage: str, event: str, status: str, **context: Any) -> None:
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is None or cycle.status in {"ready", "cancelled", "superseded"}:
            return
        cycle.events = [*(cycle.events or []), _event_payload(stage, event, status, context)][-500:]
        cycle.stage = stage
        cycle.heartbeat_at = datetime.now(UTC)
        if status == "waiting" and cycle.status != "needs_attention":
            cycle.status = "waiting"
        elif status in {"started", "observed", "retrying"} and cycle.status == "starting":
            cycle.status = "running"


def create_access_cycle(external_system_id: str, access_profile_id: str) -> dict[str, Any]:
    with SessionLocal.begin() as db:
        system = db.get(ExternalSystem, str(external_system_id))
        profile = db.get(ExternalAccessProfile, str(access_profile_id))
        if system is None or profile is None or not profile.active:
            raise ValueError("Sistema externo ou perfil de acesso inválido.")
        if profile.external_system_id != system.id:
            raise ValueError("O perfil de acesso não pertence ao sistema externo.")
        entry_url = normalize_external_entry_url((system.config or {}).get("entry_url"))
        if not entry_url:
            raise ValueError("O sistema externo não possui entry_url configurado.")
        cycle = AccessCycle(
            id=str(uuid4()), external_system_id=system.id, access_profile_id=profile.id,
            entry_url=entry_url,
            status="starting", stage="access_start", events=[], heartbeat_at=datetime.now(UTC),
        )
        db.add(cycle)
        cycle_id = cycle.id
    _append_event(cycle_id, "access", "ACCESS_CYCLE_CREATED", "success", access_profile_id=access_profile_id, external_system_id=external_system_id, canonical_entry_url_source="ExternalSystem.entry_url", entry_url=entry_url)
    return {"access_cycle_id": cycle_id, "status": "starting", "access_profile_id": access_profile_id}


def get_access_cycle(cycle_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        cycle = db.get(AccessCycle, str(cycle_id))
        if cycle is None:
            return None
        return {
            "access_cycle_id": cycle.id, "external_system_id": cycle.external_system_id,
            "access_profile_id": cycle.access_profile_id, "status": cycle.status,
            "worker_id": cycle.worker_id,
            "browser_target_id": cycle.browser_target_id,
            "browser_context_id": cycle.browser_context_id,
            "manual_validation_pending": cycle.manual_validation_requested_at is not None,
            "attention_requested": cycle.attention_requested_at is not None,
            "attention_since": cycle.attention_since.isoformat() if cycle.attention_since else None,
            "attention_reason": cycle.attention_reason,
            "resume_requested": cycle.resume_requested_at is not None,
            "entry_url": _safe_url(cycle.entry_url),
            "stage": cycle.stage, "error_code": cycle.error_code, "error_message": cycle.error_message,
            "events": cycle.events or [],
            "created_at": cycle.created_at.isoformat() if cycle.created_at else None,
            "started_at": cycle.started_at.isoformat() if cycle.started_at else None,
            "heartbeat_at": cycle.heartbeat_at.isoformat() if cycle.heartbeat_at else None,
            "finished_at": cycle.finished_at.isoformat() if cycle.finished_at else None,
        }


async def start_persisted_access_cycle(
    external_system_id: str,
    access_profile_id: str,
    *,
    cancellation_probe: Any | None = None,
) -> dict[str, Any]:
    """Create a durable cycle and wait for the worker-owned coordinator."""
    cycle = create_access_cycle(external_system_id, access_profile_id)
    cycle_id = str(cycle["access_cycle_id"])
    executor = _WORKER_ACCESS_EXECUTOR.get()
    if executor is not None:
        await executor(cycle_id)
    while True:
        if cancellation_probe is not None and await cancellation_probe():
            raise AccessCycleError("Ciclo de acesso cancelado.", code="access_cycle_cancelled", stage="access")
        current = get_access_cycle(cycle_id)
        if current is None:
            raise AccessCycleError("Ciclo de acesso não encontrado.", code="access_cycle_missing", stage="access")
        if current.get("status") == "ready" and current.get("stage") == "external_system_ready":
            return current
        if current.get("status") in {"failed", "cancelled", "superseded"}:
            raise AccessCycleError(
                str(current.get("error_message") or "O ciclo de acesso não foi concluído."),
                code=str(current.get("error_code") or "access_cycle_failed"),
                stage=str(current.get("stage") or "access"),
            )
        await asyncio.sleep(0.5)


def claim_next_access_cycle(worker_id: str | None = None) -> str | None:
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.status == "starting").order_by(AccessCycle.created_at).with_for_update(skip_locked=True))
        if cycle is None:
            return None
        cycle.status = "running"
        cycle.worker_id = worker_id
        cycle.started_at = datetime.now(UTC)
        cycle.heartbeat_at = datetime.now(UTC)
        cycle_id = cycle.id
    _append_event(cycle_id, "access", "ACCESS_CYCLE_STARTED", "started")
    return cycle_id


def recover_stale_access_cycles(stale_before: datetime) -> int:
    """Return abandoned cycles to the pending state without touching active waits."""
    recovered = 0
    with SessionLocal.begin() as db:
        cycles = (
            db.query(AccessCycle)
            .filter(AccessCycle.status.in_(["running", "waiting", "needs_attention"]))
            .filter(AccessCycle.worker_id.is_not(None))
            .filter(AccessCycle.heartbeat_at.is_not(None), AccessCycle.heartbeat_at < stale_before)
            .with_for_update(skip_locked=True)
            .all()
        )
        for cycle in cycles:
            cycle.status = "starting"
            cycle.stage = "access_start"
            cycle.started_at = None
            cycle.heartbeat_at = datetime.now(UTC)
            cycle.worker_id = None
            cycle.attention_requested_at = None
            cycle.attention_since = None
            cycle.resume_requested_at = None
            recovered += 1
    return recovered


def touch_access_cycle(cycle_id: str, *, status: str | None = None) -> None:
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is not None and cycle.status in {"starting", "running", "waiting", "needs_attention"}:
            cycle.heartbeat_at = datetime.now(UTC)
            if status and cycle.status != "needs_attention":
                cycle.status = status


def bind_access_cycle_owner(cycle_id: str, worker_id: str) -> None:
    """Persist the worker that already owns the browser execution path."""
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is None:
            raise AccessCycleError("Ciclo de acesso não encontrado.", code="access_cycle_missing", stage="access")
        if cycle.worker_id not in {None, worker_id}:
            raise AccessCycleError("Ciclo de acesso já pertence a outro worker.", code="access_cycle_owner_conflict", stage="access")
        if cycle.status in {"ready", "failed", "cancelled", "superseded"}:
            raise AccessCycleError("Ciclo de acesso não está ativo.", code="access_cycle_not_active", stage="access")
        cycle.worker_id = worker_id
        cycle.heartbeat_at = datetime.now(UTC)


def request_access_attention(cycle_id: str, *, reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Request a worker-owned hold without changing terminal or ownership state."""
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is None:
            raise AccessCycleError("Ciclo de acesso não encontrado.", code="access_cycle_missing", stage="access")
        if cycle.status in {"ready", "failed", "cancelled", "superseded"}:
            raise AccessCycleError("Ciclo de acesso não está ativo.", code="access_cycle_not_active", stage="access")
        if not cycle.worker_id:
            raise AccessCycleError("Ciclo de acesso ainda não possui worker owner.", code="access_cycle_owner_missing", stage="access")
        if cycle.status != "needs_attention" and cycle.attention_requested_at is None:
            cycle.attention_requested_at = datetime.now(UTC)
            cycle.attention_reason = str(reason or "operator_requested")[:128]
            cycle.attention_details = {
                str(key): value
                for key, value in (details or {}).items()
                if not any(secret_word in str(key).casefold() for secret_word in ("password", "token", "cookie", "secret", "authorization"))
                and isinstance(value, (str, int, float, bool, type(None)))
            }
            cycle.heartbeat_at = datetime.now(UTC)
    return get_access_cycle(cycle_id) or {"access_cycle_id": cycle_id, "status": "running"}


def request_access_resume(cycle_id: str) -> dict[str, Any]:
    """Signal the current owner to reobserve the current page."""
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is None:
            raise AccessCycleError("Ciclo de acesso não encontrado.", code="access_cycle_missing", stage="access")
        if cycle.status != "needs_attention" or not cycle.worker_id:
            raise AccessCycleError("Ciclo de acesso não está em atenção retomável.", code="access_cycle_not_in_attention", stage="access")
        cycle.resume_requested_at = datetime.now(UTC)
        cycle.heartbeat_at = datetime.now(UTC)
    return get_access_cycle(cycle_id) or {"access_cycle_id": cycle_id, "status": "needs_attention"}


def finish_access_cycle(cycle_id: str, *, status: str, error_code: str | None = None, error_message: str | None = None) -> None:
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is None or cycle.status in {"ready", "cancelled", "superseded"}:
            return
        cycle.status = status
        cycle.error_code = error_code
        cycle.error_message = error_message
        if status == "ready":
            cycle.stage = "external_system_ready"
        cycle.finished_at = datetime.now(UTC)
        cycle.heartbeat_at = datetime.now(UTC)


def _mark_manual_validation_waiting(cycle_id: str, *, stage: str, code: str, message: str) -> None:
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == cycle_id).with_for_update())
        if cycle is None or cycle.status in {"ready", "cancelled", "superseded"}:
            return
        if cycle.status != "needs_attention":
            cycle.status = "waiting"
        cycle.stage = stage
        cycle.error_code = code
        cycle.error_message = message
        cycle.finished_at = None
        cycle.heartbeat_at = datetime.now(UTC)


async def validate_manual_access_cycle(cycle_id: str) -> dict[str, Any]:
    """Queue validation on the worker that owns the page; HTTP never runs it."""
    with SessionLocal.begin() as db:
        cycle = db.scalar(select(AccessCycle).where(AccessCycle.id == str(cycle_id)).with_for_update())
        if cycle is None:
            raise AccessCycleError("Ciclo não encontrado.", code="access_cycle_missing", stage="access")
        if cycle.status == "ready":
            return {"status": "ready", "validated": True}
        if cycle.status not in {"running", "waiting", "needs_attention"} or not cycle.browser_target_id:
            raise AccessCycleError("Este ciclo não possui uma sessão ativa para validar. Inicie um novo acesso pelo perfil.", code="ACCESS_CYCLE_SESSION_UNAVAILABLE", stage="access")
        active_access_profile_public(cycle.access_profile_id)
        cycle.manual_validation_requested_at = datetime.now(UTC)
    return {"status": "validation_requested", "validated": False, "message": "Validação solicitada. Aguardando a verificação da sessão atual."}


async def validate_current_profile_session(profile_id: str) -> dict[str, Any]:
    """Passive observation of an owned target, never the global desktop page."""
    profile = active_access_profile_public(profile_id)
    with SessionLocal() as db:
        cycle = db.scalar(select(AccessCycle).where(
            AccessCycle.access_profile_id == profile_id,
            AccessCycle.browser_target_id.is_not(None),
        ).order_by(AccessCycle.created_at.desc()).limit(1))
        system = db.get(ExternalSystem, profile["external_system_id"])
        config = dict(system.config or {}) if system else {}
        target_id = cycle.browser_target_id if cycle else None
        context_id = cycle.browser_context_id if cycle else None
    if not target_id or not context_id:
        return {"profile": profile, "available": False, "diagnostic": {"reason": "profile_session_not_observed"}}
    try:
        endpoint = await asyncio.to_thread(_desktop_version)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(endpoint["webSocketDebuggerUrl"])
            for context in browser.contexts:
                for page in context.pages:
                    if page.is_closed():
                        continue
                    identity = await browser_page_identity(context, page)
                    if identity != {"target_id": target_id, "context_id": context_id}:
                        continue
                    expected_host = str(config.get("expected_system_host") or "").lower().rstrip(".")
                    if expected_host and url_host(page.url).lower().rstrip(".") == expected_host:
                        identity_result = await _identity_evidence(page, profile, config)
                        if identity_result.status == "match":
                            from backend.services.access_profiles import record_profile_validation
                            confirmed = record_profile_validation(profile_id, status="verified", reason="passive_identity_verified", identity_evidence=list(identity_result.evidence))
                            return {"profile": confirmed, "available": True, "diagnostic": {"reason": "identity_verified"}}
                    return {"profile": profile, "available": False, "diagnostic": {"reason": "current_identity_not_confirmed"}}
    except Exception as exc:
        logger.warning("Observação passiva indisponível profile=%s exception=%s", profile_id, type(exc).__name__)
    return {"profile": profile, "available": False, "diagnostic": {"reason": "profile_session_not_observed"}}


async def _validate_owned_access_cycle(cycle_id: str, identity_session: BrowserIdentitySession, page: Any) -> dict[str, Any]:
    """Worker-only validation after its coordinator task has been stopped."""
    with SessionLocal() as db:
        cycle = db.get(AccessCycle, str(cycle_id))
        if cycle is None:
            raise AccessCycleError("Ciclo de acesso não encontrado.", code="access_cycle_missing", stage="access")
        if cycle.status == "ready" and cycle.stage == "external_system_ready":
            return {"status": "ready", "validated": True, "access_cycle": get_access_cycle(cycle_id)}
        allowed_failed = {
            "reauthentication_required",
            "account_picker_skipped",
            "access_authentication_not_completed",
            "ACCESS_IDENTITY_NOT_OBSERVED",
            "access_identity_mismatch",
        }
        if cycle.status not in {"starting", "running", "waiting", "needs_attention"} and cycle.error_code not in allowed_failed:
            raise AccessCycleError(
                "Este ciclo não está aguardando validação manual.",
                code="access_cycle_not_waiting_manual_validation",
                stage=str(cycle.stage or "access"),
            )
        system = db.get(ExternalSystem, cycle.external_system_id)
        profile = db.get(ExternalAccessProfile, cycle.access_profile_id)
        config = dict(system.config or {}) if system else {}
        profile_id = cycle.access_profile_id
    if system is None or profile is None or not profile_id:
        raise AccessCycleError("Contexto de acesso não encontrado.", code="access_context_invalid", stage="access")
    profile_data = active_access_profile_public(profile_id)
    if identity_session.access_profile_id != profile_id or page.context != identity_session.context:
        raise AccessCycleError("Sessão não pertence ao perfil solicitado.", code="ACCESS_IDENTITY_MISMATCH", stage="access_identity")
    expected_host = str(config.get("expected_system_host") or "").strip().lower().rstrip(".")
    _append_event(cycle_id, "manual_access_validation", "MANUAL_ACCESS_VALIDATION_STARTED", "started", access_profile_id=profile_id)
    try:
        current_host = url_host(str(getattr(page, "url", "") or "")).lower().rstrip(".")
        if not expected_host or current_host != expected_host:
            body = await _body_text(page)
            auth_state = classify_microsoft_auth_state(body)
            message = "Finalize a autenticação no navegador antes de validar o acesso."
            _append_event(
                cycle_id,
                "manual_access_validation",
                "ACCESS_AUTHENTICATION_NOT_COMPLETED",
                "waiting",
                access_profile_id=profile_id,
                host=current_host,
                path=str(getattr(page, "url", "") or ""),
                auth_state=auth_state,
            )
            _mark_manual_validation_waiting(cycle_id, stage="manual_authentication", code="ACCESS_AUTHENTICATION_NOT_COMPLETED", message=message)
            return {"status": "waiting", "validated": False, "code": "ACCESS_AUTHENTICATION_NOT_COMPLETED", "message": message, "access_cycle": get_access_cycle(cycle_id)}

        _append_event(cycle_id, "access_identity", "ACCESS_IDENTITY_VERIFICATION_STARTED", "started", access_profile_id=profile_id)
        identity_result = await _identity_evidence(page, profile_data, {"identity_selector": str(config.get("identity_selector") or "")})
        if identity_result.status == "unknown":
            message = "A identidade ainda não está disponível. Aguarde o carregamento do sistema e tente novamente."
            _append_event(cycle_id, "access_identity", "ACCESS_IDENTITY_VERIFICATION_PENDING", "waiting", access_profile_id=profile_id, host=current_host)
            _mark_manual_validation_waiting(cycle_id, stage="access_identity", code="ACCESS_IDENTITY_NOT_OBSERVED", message=message)
            return {"status": "waiting", "validated": False, "code": "ACCESS_IDENTITY_NOT_OBSERVED", "message": message, "access_cycle": get_access_cycle(cycle_id)}
        if identity_result.status == "mismatch":
            message = "A identidade exibida não corresponde ao perfil de acesso selecionado."
            _append_event(cycle_id, "access_identity", "ACCESS_IDENTITY_MISMATCH", "failed", access_profile_id=profile_id, host=current_host)
            _mark_manual_validation_waiting(cycle_id, stage="access_identity", code="ACCESS_IDENTITY_MISMATCH", message=message)
            return {"status": "waiting", "validated": False, "code": "ACCESS_IDENTITY_MISMATCH", "message": message, "access_cycle": get_access_cycle(cycle_id)}

        _append_event(cycle_id, "access_identity", "ACCESS_IDENTITY_VERIFIED", "success", access_profile_id=profile_id, host=current_host)
        await identity_session.persist()
        _append_event(cycle_id, "manual_access_validation", "ACCESS_SESSION_PERSISTED", "success", access_profile_id=profile_id)
        from backend.services.access_profiles import record_profile_validation

        validated_profile = record_profile_validation(profile_id, status="verified", reason="manual_access_validated", identity_evidence=list(identity_result.evidence))
        _append_event(cycle_id, "manual_access_validation", "MANUAL_ACCESS_VALIDATION_COMPLETED", "success", access_profile_id=profile_id)
        _append_event(cycle_id, "external_system_ready", "EXTERNAL_SYSTEM_READY", "success", access_profile_id=profile_id, host=current_host)
        _append_event(cycle_id, "external_system_ready", "ACCESS_CYCLE_COMPLETED", "success", access_profile_id=profile_id)
        finish_access_cycle(cycle_id, status="ready")
        return {"status": "ready", "validated": True, "profile": validated_profile, "access_cycle": get_access_cycle(cycle_id)}
    finally:
        with SessionLocal.begin() as db:
            cycle = db.get(AccessCycle, cycle_id)
            if cycle is not None:
                cycle.manual_validation_requested_at = None


async def _coordinate_owned_access(
    cycle_id: str,
    identity_session: BrowserIdentitySession,
    page: Any,
    coordinator: Any = None,
    *,
    coordinator_factory: Any | None = None,
) -> None:
    """Serialize automation, attention, and manual validation on one live page."""
    if coordinator_factory is None:
        used_initial = False

        def coordinator_factory(reobserve_current_page: bool = False) -> Any:
            nonlocal used_initial
            if reobserve_current_page or used_initial:
                raise AccessCycleError(
                    "Este ciclo não possui uma fábrica de retomada worker-owned.",
                    code="access_cycle_resume_unavailable",
                    stage="access",
                )
            used_initial = True
            return coordinator

    async def start_coordinator(*, reobserve_current_page: bool = False) -> asyncio.Task[Any]:
        value = coordinator_factory(reobserve_current_page)
        if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
            return asyncio.create_task(value)
        return asyncio.create_task(value)

    task = await start_coordinator()
    task_is_resume = False
    try:
        while True:
            with SessionLocal() as db:
                cycle = db.get(AccessCycle, cycle_id)
                if cycle is None or cycle.status in {"cancelled", "superseded", "ready"}:
                    return
                requested = cycle.manual_validation_requested_at is not None
                attention_requested = cycle.attention_requested_at is not None
                in_attention = cycle.status == "needs_attention"
                resume_requested = cycle.resume_requested_at is not None
            if requested:
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError, AccessCycleError):
                        await task
                    task = None
                result = await _validate_owned_access_cycle(cycle_id, identity_session, page)
                if result["validated"]:
                    return
                # No automation restart after human takeover. Wait for the
                # next explicit validation on this same page.
            elif attention_requested and not in_attention:
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError, AccessCycleError):
                        await task
                    task = None
                with SessionLocal.begin() as db:
                    cycle = db.get(AccessCycle, cycle_id)
                    if cycle is not None and cycle.status not in {"ready", "cancelled", "superseded"}:
                        cycle.status = "needs_attention"
                        cycle.stage = "access_attention"
                        cycle.attention_since = cycle.attention_since or datetime.now(UTC)
                        cycle.error_code = "ACCESS_CYCLE_NEEDS_ATTENTION"
                        cycle.error_message = cycle.attention_reason or "Atenção do operador solicitada."
                        cycle.finished_at = None
                        cycle.heartbeat_at = datetime.now(UTC)
                        cycle.attention_requested_at = None
                _append_event(cycle_id, "access_attention", "ACCESS_ATTENTION_ENTERED", "waiting")
            elif in_attention:
                if resume_requested:
                    with SessionLocal.begin() as db:
                        cycle = db.get(AccessCycle, cycle_id)
                        if cycle is not None and cycle.status == "needs_attention":
                            cycle.status = "running"
                            cycle.stage = "access_resuming"
                            cycle.resume_requested_at = None
                            cycle.attention_since = None
                            cycle.error_code = None
                            cycle.error_message = None
                            cycle.heartbeat_at = datetime.now(UTC)
                    _append_event(cycle_id, "access_attention", "ACCESS_ATTENTION_RESUMING", "started")
                    task = await start_coordinator(reobserve_current_page=True)
                    task_is_resume = True
                elif task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError, AccessCycleError):
                        await task
                    task = None
            elif task is not None and task.done():
                try:
                    await task
                except AccessCycleError as exc:
                    if exc.code not in {"account_picker_skipped", "account_picker_selection_lost", "reauthentication_required", "access_authentication_not_completed", "access_identity_mismatch"}:
                        raise
                    if task_is_resume:
                        with SessionLocal.begin() as db:
                            cycle = db.get(AccessCycle, cycle_id)
                            if cycle is not None and cycle.status not in {"ready", "cancelled", "superseded"}:
                                cycle.status = "needs_attention"
                                cycle.stage = "access_attention"
                                cycle.attention_since = datetime.now(UTC)
                                cycle.attention_reason = exc.code
                                cycle.error_code = exc.code
                                cycle.error_message = str(exc)
                                cycle.heartbeat_at = datetime.now(UTC)
                        _append_event(cycle_id, "access_attention", "ACCESS_ATTENTION_REENTERED", "waiting", reason=exc.code)
                    else:
                        _mark_manual_validation_waiting(cycle_id, stage="manual_authentication", code=exc.code, message=str(exc))
                    task = None
                    task_is_resume = False
                else:
                    await identity_session.persist()
                    from backend.services.access_profiles import record_profile_validation
                    result = task.result()
                    record_profile_validation(identity_session.access_profile_id, status="verified", reason="access_identity_verified", identity_evidence=list(getattr(result, "identity_evidence", ()) or ()))
                    finish_access_cycle(cycle_id, status="ready")
                    return
            await asyncio.sleep(0.25)
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, AccessCycleError):
                await task


async def execute_access_cycle(cycle_id: str) -> None:
    with SessionLocal() as db:
        cycle = db.get(AccessCycle, cycle_id)
        if cycle is None:
            return
        system = db.get(ExternalSystem, cycle.external_system_id)
        profile = db.get(ExternalAccessProfile, cycle.access_profile_id)
        config = dict(system.config or {}) if system else {}
        profile_data = active_access_profile_public(cycle.access_profile_id) if profile else None
    if system is None or profile is None or profile_data is None:
        finish_access_cycle(cycle_id, status="failed", error_code="access_context_invalid", error_message="Contexto de acesso não encontrado.")
        return
    playwright = None
    identity_session: BrowserIdentitySession | None = None
    try:
        existing = _LIVE_PROFILE_SESSIONS.get(profile.id)
        if existing is not None and existing[1].browser.is_connected():
            playwright, identity_session = existing
        else:
            if existing is not None:
                await existing[0].stop()
            playwright = await async_playwright().start()
            connection = await browser_provider("desktop_browser").connect(playwright, f"access-cycle-{cycle_id}")
            identity_session = BrowserIdentitySession(
                connection.context, profile.id, browser=connection.browser, scope=desktop_cdp_url(),
            )
            await identity_session.activate()
            _LIVE_PROFILE_SESSIONS[profile.id] = (playwright, identity_session)
        page = await identity_session.page()
        identity = await browser_page_identity(identity_session.context, page)
        with SessionLocal.begin() as db:
            bound = db.get(AccessCycle, cycle_id)
            bound.browser_target_id = identity["target_id"]
            bound.browser_context_id = identity["context_id"]
        await page.bring_to_front()
        timeline = lambda stage, event, status, **context: _append_event(cycle_id, stage, event, status, **context)
        def coordinator_factory(reobserve_current_page: bool = False) -> Any:
            return ensure_access_cycle(
                page,
                external_system={
                    "id": system.id,
                    "entry_url": cycle.entry_url,
                    "expected_system_host": str(config.get("expected_system_host") or ""),
                    "identity_selector": str(config.get("identity_selector") or ""),
                    "run_start_strategy": str(config.get("run_start_strategy") or "external_entry_each_run"),
                },
                access_profile=profile_data,
                action={"access_bootstrap": config.get("access_bootstrap") or []},
                timeline=timeline,
                require_external_system=True,
                reobserve_current_page=reobserve_current_page,
            )

        await _coordinate_owned_access(
            cycle_id,
            identity_session,
            page,
            coordinator_factory=coordinator_factory,
        )
    except AccessCycleError as exc:
        logger.warning("Ciclo de acesso %s terminou: %s", cycle_id, exc.code)
        finish_access_cycle(cycle_id, status="failed", error_code=exc.code, error_message=str(exc))
    except BrowserProviderError as exc:
        logger.warning("Ciclo de acesso %s sem isolamento de browser: %s", cycle_id, exc)
        finish_access_cycle(cycle_id, status="failed", error_code=getattr(exc, "code", "ACCESS_PROFILE_BROWSER_ISOLATION_UNAVAILABLE"), error_message=str(exc))
    except Exception:
        logger.exception("Falha no ciclo de acesso %s", cycle_id)
        finish_access_cycle(cycle_id, status="failed", error_code="access_cycle_failed", error_message="Falha operacional no ciclo de acesso.")
    finally:
        # Keep the profile's actual page alive for human interaction and
        # downstream handoff. Never save an unverified session on failure.
        if playwright is not None and profile.id not in _LIVE_PROFILE_SESSIONS:
            await playwright.stop()


async def ensure_access_cycle(*args: Any, **kwargs: Any):
    """Single in-process entry point for learning and execution boundaries."""
    return await start_canonical_access(*args, **kwargs)
