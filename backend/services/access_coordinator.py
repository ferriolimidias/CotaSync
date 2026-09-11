"""Canonical external-access state machine.

This module owns only the access boundary of a logical unit.  Main action
steps are deliberately outside this coordinator.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.services.action_pages import url_host
from backend.services.runtime_wait import RuntimeWaitTerminal, wait_for_runtime_state
from backend.services.session_guardian import SessionGuardian
from backend.services.start_policy import (
    EXTERNAL_ENTRY_EACH_RUN,
    normalize_external_entry_url,
    resolve_external_entry_url,
    validate_fresh_start_context,
)


Timeline = Callable[..., Any]


def _emit(timeline: Timeline | None, stage: str, event: str, status: str, **context: Any) -> None:
    if timeline is not None:
        timeline(stage, event, status, **context)


def _safe_page_path(page: Any) -> str:
    try:
        return str(getattr(page, "url", "") or "")
    except Exception:
        return ""


_MICROSOFT_HOSTS = {
    "login.microsoftonline.com",
    "login.microsoft.com",
    "login.live.com",
    "login.windows.net",
    "m365.cloud.microsoft",
}


def build_microsoft_entry_url(entry_url: str) -> str:
    """Force explicit account selection without discarding OAuth parameters."""
    raw = normalize_external_entry_url(entry_url)
    parsed = urlsplit(raw)
    host = str(parsed.hostname or "").casefold()
    if host not in _MICROSOFT_HOSTS and not any(host.endswith(f".{item}") for item in _MICROSOFT_HOSTS):
        return raw
    params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in {"login_hint", "domain_hint", "prompt"}]
    params.append(("prompt", "select_account"))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment))


async def _body_text(page: Any) -> str:
    try:
        return str(await page.locator("body").inner_text(timeout=750))[:20_000]
    except Exception:
        return ""


def _page_scopes(page: Any) -> list[Any]:
    """Return the page and child frames where Microsoft renders auth UI."""
    scopes = [page]
    try:
        scopes.extend(frame for frame in page.frames if frame is not page)
    except Exception:
        pass
    return scopes


def _is_account_picker_scope(scope: Any, text: str) -> bool:
    try:
        scope_url = str(getattr(scope, "url", "") or "").casefold()
    except Exception:
        scope_url = ""
    normalized = str(text or "").casefold()
    return (
        "savedusers" in scope_url
        or "pick an account" in normalized
        or "escolha uma conta" in normalized
        or "selecionar uma conta" in normalized
    )


async def _visible(page: Any, selector: str) -> bool:
    try:
        locator = page.locator(selector).first
        return await locator.count() > 0 and await locator.is_visible()
    except Exception:
        return False


async def _identity_evidence(page: Any, profile: dict[str, Any], system: dict[str, Any]) -> bool:
    """Verify deterministic identity evidence without treating host as identity."""
    expected = [
        str(profile.get("login_identifier") or "").strip(),
        str(profile.get("display_name") or "").strip(),
    ]
    expected = [item.casefold() for item in expected if item]
    selector = str(system.get("identity_selector") or "").strip()
    if selector:
        try:
            observed = str(await page.locator(selector).first.inner_text(timeout=1000)).casefold()
        except Exception:
            return False
        return bool(expected and any(item in observed for item in expected))
    body = (await _body_text(page)).casefold()
    return bool(expected and any(item in body for item in expected))


@dataclass
class AccessCycleResult:
    state: str
    page: Any
    entry_url: str
    bootstrap_events: list[dict[str, Any]] = field(default_factory=list)
    profile_selected: bool = False


class AccessCycleError(RuntimeError):
    def __init__(self, message: str, *, code: str, stage: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


class CanonicalAccessCoordinator:
    """Run the same external-entry/account/bootstrap sequence everywhere."""

    def __init__(self, guardian: SessionGuardian | None = None) -> None:
        self.guardian = guardian or SessionGuardian()

    async def start(
        self,
        page: Any,
        *,
        external_system: dict[str, Any] | None,
        access_profile: dict[str, Any] | None,
        action: dict[str, Any] | None = None,
        timeline: Timeline | None = None,
        cancellation_probe: Callable[[], Any] | None = None,
        terminal_probe: Callable[[], Any] | None = None,
        same_logical_unit: bool = False,
        require_external_system: bool = True,
    ) -> AccessCycleResult:
        system = external_system if isinstance(external_system, dict) else {}
        profile = access_profile if isinstance(access_profile, dict) else {}
        config = action if isinstance(action, dict) else {}
        strategy = str(config.get("run_start_strategy") or system.get("run_start_strategy") or EXTERNAL_ENTRY_EACH_RUN).strip()
        profile_id = str(profile.get("id") or config.get("required_access_profile_id") or "").strip()
        identifier = str(profile.get("login_identifier") or config.get("access_profile_email_or_identifier") or "").strip()
        entry_url = resolve_external_entry_url(system)
        effective_entry_url = build_microsoft_entry_url(entry_url)
        context = validate_fresh_start_context(
            strategy=strategy,
            entry_url=entry_url,
            access_profile_id=profile_id,
        )
        if not context.get("valid"):
            raise AccessCycleError(
                "O contexto de acesso externo não está completo.",
                code=str(context.get("code") or "access_context_invalid"),
                stage="access_start",
            )
        if same_logical_unit and strategy == EXTERNAL_ENTRY_EACH_RUN:
            return AccessCycleResult("external_system_ready", page, entry_url, profile_selected=True)
        if strategy != EXTERNAL_ENTRY_EACH_RUN:
            return AccessCycleResult("external_system_ready", page, entry_url, profile_selected=bool(profile_id))
        if not identifier:
            raise AccessCycleError("O perfil de acesso não possui login_identifier.", code="access_identifier_missing", stage="account_picker")

        _emit(timeline, "access", "ACCESS_CYCLE_STARTED", "started", access_profile_id=profile_id)
        try:
            _emit(
                timeline,
                "external_entry",
                "CANONICAL_ENTRY_NAVIGATION_STARTED",
                "started",
                canonical_entry_url_source="ExternalSystem.entry_url",
                entry_url=entry_url,
            )
            _emit(timeline, "external_entry", "EXTERNAL_ENTRY_STARTED", "started", entry_url=entry_url)
            try:
                await page.goto(effective_entry_url, wait_until="domcontentloaded", timeout=5000)
            except Exception:
                expected_host = url_host(effective_entry_url)
                await wait_for_runtime_state(
                    lambda: bool(expected_host and url_host(_safe_page_path(page)) == expected_host),
                    state_name="entrada externa",
                    terminal_probe=terminal_probe,
                    cancellation_probe=cancellation_probe,
                    on_waiting=lambda name: _emit(timeline, "external_entry", "WAITING_EXTERNAL_SYSTEM", "waiting", wait_target=name),
                )
            _emit(
                timeline,
                "external_entry",
                "CANONICAL_ENTRY_NAVIGATION_COMPLETED",
                "success",
                canonical_entry_url_source="ExternalSystem.entry_url",
                entry_url=entry_url,
                host=url_host(_safe_page_path(page)),
                path=_safe_page_path(page),
            )
            _emit(timeline, "external_entry", "EXTERNAL_ENTRY_COMPLETED", "success", host=url_host(_safe_page_path(page)), path=_safe_page_path(page))

            picker = {"observed": False}
            picker_restart_count = 0

            async def observe_picker() -> bool:
                nonlocal picker_restart_count
                if not hasattr(page, "locator"):
                    picker["observed"] = "microsoft" in _safe_page_path(page).casefold()
                    return True
                scope_texts = [(scope, await _body_text(scope)) for scope in _page_scopes(page)]
                text = "\n".join(value for _, value in scope_texts)
                state = await self.guardian.classify(page, {**config, "access_profile_email_or_identifier": identifier, "microsoft_saved_account_identifier": identifier})
                is_picker = state.state == "microsoft_pick_account" or any(
                    _is_account_picker_scope(scope, value) for scope, value in scope_texts
                )
                if is_picker:
                    picker["observed"] = True
                    _emit(timeline, "access", "ACCOUNT_PICKER_OBSERVED", "observed", access_profile_id=profile_id, host=url_host(_safe_page_path(page)), path=_safe_page_path(page))
                    return True
                direct_states = {"microsoft_consent_required", "authenticated_system"}
                direct_external = state.state in direct_states or url_host(_safe_page_path(page)) == str(system.get("expected_system_host") or "").strip()
                if direct_external:
                    if picker_restart_count < 1:
                        picker_restart_count += 1
                        _emit(timeline, "access", "ACCOUNT_PICKER_SKIPPED", "retrying", access_profile_id=profile_id)
                        _emit(
                            timeline,
                            "external_entry",
                            "CANONICAL_ENTRY_NAVIGATION_STARTED",
                            "retrying",
                            canonical_entry_url_source="ExternalSystem.entry_url",
                            entry_url=entry_url,
                        )
                        await page.goto(effective_entry_url, wait_until="domcontentloaded", timeout=5000)
                        return False
                    raise AccessCycleError(
                        "A entrada Microsoft não apresentou o Account Picker para este novo ciclo.",
                        code="account_picker_skipped",
                        stage="account_picker",
                    )
                return False

            await wait_for_runtime_state(
                observe_picker,
                state_name="Account Picker",
                terminal_probe=terminal_probe,
                cancellation_probe=cancellation_probe,
                on_waiting=lambda name: _emit(timeline, "access", "WAITING_EXTERNAL_SYSTEM", "waiting", wait_target=name),
            )

            selected = False
            if picker["observed"]:
                _emit(timeline, "access", "ACCESS_PROFILE_SELECTION_STARTED", "started", access_profile_id=profile_id)
                selection_restart_count = 0

                async def select_profile() -> bool:
                    nonlocal selected, selection_restart_count
                    if selected:
                        return True
                    state = await self.guardian.classify(
                        page,
                        {**config, "access_profile_email_or_identifier": identifier, "microsoft_saved_account_identifier": identifier},
                    )
                    scope_texts = [(scope, await _body_text(scope)) for scope in _page_scopes(page)]
                    text = "\n".join(value for _, value in scope_texts)
                    picker_still_visible = state.state == "microsoft_pick_account" or any(
                        _is_account_picker_scope(scope, value) for scope, value in scope_texts
                    )
                    if not picker_still_visible:
                        # A pre-existing Microsoft session must never become a
                        # successful profile selection for this logical unit.
                        if selection_restart_count < 1:
                            selection_restart_count += 1
                            _emit(timeline, "access", "ACCOUNT_PICKER_SELECTION_LOST", "retrying", access_profile_id=profile_id)
                            _emit(
                                timeline,
                                "external_entry",
                                "CANONICAL_ENTRY_NAVIGATION_STARTED",
                                "retrying",
                                canonical_entry_url_source="ExternalSystem.entry_url",
                                entry_url=entry_url,
                            )
                            await page.goto(effective_entry_url, wait_until="domcontentloaded", timeout=5000)
                            return False
                        raise AccessCycleError(
                            "O Account Picker deixou de estar disponível antes da seleção explícita do perfil.",
                            code="account_picker_selection_lost",
                            stage="account_picker",
                        )
                    selection_action = {
                        "microsoft_saved_account_identifier": identifier,
                        "access_profile_email_or_identifier": identifier,
                        "microsoft_saved_account_text": identifier,
                    }
                    selected = False
                    for scope in _page_scopes(page):
                        if await self.guardian.click_configured_saved_account(scope, selection_action):
                            selected = True
                            break
                    return selected

                await wait_for_runtime_state(
                    select_profile,
                    state_name="seleção do perfil de acesso",
                    terminal_probe=terminal_probe,
                    cancellation_probe=cancellation_probe,
                    on_waiting=lambda name: _emit(timeline, "access", "WAITING_EXTERNAL_SYSTEM", "waiting", wait_target=name),
                )

                async def confirm_selection() -> bool:
                    if not hasattr(page, "locator"):
                        return True
                    scope_texts = [(scope, await _body_text(scope)) for scope in _page_scopes(page)]
                    text = "\n".join(value for _, value in scope_texts)
                    state = await self.guardian.classify(page, {**config, "access_profile_email_or_identifier": identifier})
                    picker_visible = state.state == "microsoft_pick_account" or any(
                        _is_account_picker_scope(scope, value) for scope, value in scope_texts
                    )
                    return not picker_visible

                await wait_for_runtime_state(
                    confirm_selection,
                    state_name="confirmação do perfil de acesso",
                    terminal_probe=terminal_probe,
                    cancellation_probe=cancellation_probe,
                    on_waiting=lambda name: _emit(timeline, "access", "WAITING_EXTERNAL_SYSTEM", "waiting", wait_target=name),
                )
                _emit(timeline, "access", "ACCESS_PROFILE_SELECTION_COMPLETED", "success", access_profile_id=profile_id)
            else:
                _emit(timeline, "access", "ACCESS_PROFILE_SELECTION_COMPLETED", "success", access_profile_id=profile_id, detail="entry_auto_selected")

            raw_bootstrap = config.get("access_bootstrap")
            bootstrap = raw_bootstrap if isinstance(raw_bootstrap, list) else []
            _emit(timeline, "access_bootstrap", "ACCESS_BOOTSTRAP_STARTED", "started", access_profile_id=profile_id)
            events: list[dict[str, Any]] = []
            for index, item in enumerate(bootstrap):
                if not isinstance(item, dict) or str(item.get("event_type") or "").casefold() not in {"click", "clicar"}:
                    raise AccessCycleError("Bootstrap de acesso inválido.", code="access_bootstrap_event_invalid", stage="access_bootstrap")
                selector = str(item.get("selector") or "").strip()
                if not selector:
                    raise AccessCycleError("Bootstrap de acesso sem selector.", code="access_bootstrap_selector_missing", stage="access_bootstrap")
                _emit(timeline, "access_bootstrap", "ACCESS_BOOTSTRAP_STEP_STARTED", "started", access_profile_id=profile_id, step_index=index, operation="click", selector=selector)
                await wait_for_runtime_state(
                    lambda selector=selector: _visible(page, selector),
                    state_name=f"bootstrap de acesso {index}",
                    terminal_probe=terminal_probe,
                    cancellation_probe=cancellation_probe,
                    on_waiting=lambda name: _emit(timeline, "access_bootstrap", "WAITING_EXTERNAL_SYSTEM", "waiting", wait_target=name),
                )
                try:
                    await page.locator(selector).first.click(timeout=1000)
                except Exception as exc:
                    raise AccessCycleError("Não foi possível executar o bootstrap de acesso.", code="access_bootstrap_click_failed", stage="access_bootstrap") from exc
                events.append({"event": "access_bootstrap", "bootstrap_index": index, "event_type": "click", "selector_present": True, "status": "success"})
                _emit(timeline, "access_bootstrap", "ACCESS_BOOTSTRAP_STEP_COMPLETED", "success", access_profile_id=profile_id, step_index=index, operation="click", selector=selector)
            _emit(timeline, "access_bootstrap", "ACCESS_BOOTSTRAP_COMPLETED", "success", access_profile_id=profile_id)
            if require_external_system:
                expected_host = str(system.get("expected_system_host") or config.get("expected_system_host") or "").strip()

                async def system_ready() -> bool:
                    current_host = url_host(_safe_page_path(page))
                    return bool(current_host and (not expected_host or current_host == expected_host))

                await wait_for_runtime_state(
                    system_ready,
                    state_name="sistema externo",
                    terminal_probe=terminal_probe,
                    cancellation_probe=cancellation_probe,
                    on_waiting=lambda name: _emit(timeline, "access", "WAITING_EXTERNAL_SYSTEM", "waiting", wait_target=name),
                )
            _emit(timeline, "access_identity", "ACCESS_IDENTITY_VERIFICATION_STARTED", "started", access_profile_id=profile_id)
            identity_verified = await _identity_evidence(page, profile, system)
            if not identity_verified:
                _emit(timeline, "access_identity", "ACCESS_IDENTITY_MISMATCH", "failed", access_profile_id=profile_id)
                raise AccessCycleError(
                    "A identidade externa ativa não corresponde ao perfil de acesso.",
                    code="access_identity_mismatch",
                    stage="access_identity",
                )
            _emit(timeline, "access_identity", "ACCESS_IDENTITY_VERIFIED", "success", access_profile_id=profile_id)
            _emit(timeline, "access", "EXTERNAL_SYSTEM_READY", "success", access_profile_id=profile_id, host=url_host(_safe_page_path(page)), path=_safe_page_path(page))
            _emit(timeline, "access", "ACCESS_CYCLE_COMPLETED", "success", access_profile_id=profile_id)
            return AccessCycleResult("external_system_ready", page, effective_entry_url, events, profile_selected=selected)
        except (AccessCycleError, RuntimeWaitTerminal):
            raise
        except Exception as exc:
            raise AccessCycleError("Falha no ciclo de acesso externo.", code="access_cycle_failed", stage="access") from exc


async def start_canonical_access(*args: Any, guardian: SessionGuardian | None = None, **kwargs: Any) -> AccessCycleResult:
    return await CanonicalAccessCoordinator(guardian=guardian).start(*args, **kwargs)
