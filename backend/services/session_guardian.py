"""Session state classification and recovery for desktop browser actions."""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from backend.services.action_pages import expected_action_hosts, is_reauthentication_url, url_host


SESSION_STATES = {
    "authenticated_system",
    "microsoft_pick_account",
    "microsoft_password_required",
    "microsoft_mfa_required",
    "microsoft_consent_required",
    "microsoft_signed_out",
    "unknown_microsoft_auth",
    "blocked_or_access_denied",
    "wrong_host",
    "system_loading",
    "system_unresponsive",
    "unknown",
}

_MICROSOFT_HOST_SUFFIXES = (
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "login.windows.net",
    "m365.cloud.microsoft",
)
_MICROSOFT_AUTH_PATH_MARKERS = (
    "login",
    "signin",
    "sign-in",
    "oauth",
    "authorize",
    "auth",
)
_PICK_ACCOUNT_WORDS = (
    "pick an account",
    "escolha uma conta",
    "selecionar uma conta",
    "use another account",
    "usar outra conta",
)
_PASSWORD_WORDS = (
    "enter password",
    "digite sua senha",
    "inserir senha",
    "senha",
    "password",
)
_MFA_WORDS = (
    "approve sign in request",
    "verify your identity",
    "verifique sua identidade",
    "authenticator",
    "autenticador",
    "multi-factor",
    "mfa",
    "código de verificação",
    "codigo de verificacao",
)
_CONSENT_WORDS = (
    "permissions requested",
    "permissões solicitadas",
    "permissoes solicitadas",
    "consent on behalf",
    "aceitar permissões",
    "aceitar permissoes",
)
_SIGNED_OUT_WORDS = (
    "signed out",
    "you've signed out",
    "você saiu",
    "voce saiu",
    "sessão encerrada",
    "sessao encerrada",
)
_BLOCKED_WORDS = (
    "access denied",
    "acesso negado",
    "acesso bloqueado",
    "blocked",
    "forbidden",
    "não é possível acessar esse site",
    "nao e possivel acessar esse site",
)
_LOADING_WORDS = (
    "carregando",
    "aguarde",
    "loading",
    "please wait",
    "processando",
)


def _env_seconds(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _safe_page_url(url: Any) -> str:
    try:
        parsed = urlsplit(str(url or ""))
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except Exception:
        return ""


def _metadata(action: Any, key: str, default: Any = None) -> Any:
    if isinstance(action, dict):
        return action.get(key, default)
    return getattr(action, key, default)


def _matches_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in words)


def _is_microsoft_host(host: str) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _MICROSOFT_HOST_SUFFIXES)


def _is_microsoft_auth_url(url: str, host: str) -> bool:
    if _is_microsoft_host(host):
        return True
    if not (host == "microsoft.com" or host.endswith(".microsoft.com")):
        return False
    try:
        path = urlsplit(url).path.casefold()
    except Exception:
        path = ""
    return any(marker in path for marker in _MICROSOFT_AUTH_PATH_MARKERS)


def configured_saved_account_texts(action: Any) -> list[str]:
    configured = [
        _metadata(action, "microsoft_saved_account_text", ""),
        _metadata(action, "microsoft_saved_account_identifier", ""),
        _metadata(action, "access_profile_email_or_identifier", ""),
    ]
    default_text = os.getenv("COTASYNC_MICROSOFT_SAVED_ACCOUNT_TEXT", "").strip()
    default_email = os.getenv("COTASYNC_MICROSOFT_SAVED_ACCOUNT_EMAIL", "").strip()
    if default_text:
        configured.append(default_text)
    if default_email:
        configured.append(default_email)
    seen: set[str] = set()
    result: list[str] = []
    for raw in configured:
        value = str(raw or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


@dataclass
class SessionGuardianConfig:
    check_timeout_seconds: int = field(
        default_factory=lambda: _env_seconds("COTASYNC_SESSION_CHECK_TIMEOUT_SECONDS", 20)
    )
    recovery_attempts: int = field(
        default_factory=lambda: _env_seconds("COTASYNC_SESSION_RECOVERY_ATTEMPTS", 3)
    )
    refresh_attempts: int = field(
        default_factory=lambda: _env_seconds("COTASYNC_SESSION_REFRESH_ATTEMPTS", 2)
    )
    recovery_backoff_seconds: int = field(
        default_factory=lambda: _env_seconds("COTASYNC_SESSION_RECOVERY_BACKOFF_SECONDS", 3)
    )


@dataclass
class PageSessionState:
    state: str
    current_host: str = ""
    current_url: str = ""
    title: str = ""
    ready_state: str = ""
    retryable: bool = False
    operator_action_required: bool = False
    reason: str = ""


@dataclass
class SessionRecoveryResult:
    ok: bool
    state: PageSessionState
    recovery_attempts: int = 0
    recovery_steps: list[dict[str, Any]] = field(default_factory=list)
    retryable: bool = False
    operator_action_required: bool = False
    recovery_attempted: bool = False

    def diagnostics(self) -> dict[str, Any]:
        return {
            "session_state": self.state.state,
            "recovery_attempts": self.recovery_attempts,
            "recovery_steps": self.recovery_steps,
            "last_page_title": self.state.title,
            "current_host": self.state.current_host,
            "retryable": self.retryable,
            "operator_action_required": self.operator_action_required,
            "recovery_attempted": self.recovery_attempted,
        }


class SessionGuardianError(RuntimeError):
    """Operational session failure with safe structured diagnostics."""

    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class SessionGuardian:
    def __init__(self, config: SessionGuardianConfig | None = None) -> None:
        self.config = config or SessionGuardianConfig()

    async def classify(
        self,
        page: Any,
        action: Any,
        *,
        authenticated: bool | None = None,
    ) -> PageSessionState:
        started = time.monotonic()
        url = _safe_page_url(getattr(page, "url", ""))
        host = url_host(url)
        title = ""
        ready_state = ""
        body_text = ""
        unreachable = False
        try:
            title = str(await page.title()).strip()[:200]
        except Exception:
            unreachable = True
        try:
            ready_state = str(await page.evaluate("() => document.readyState")).strip().lower()
        except Exception:
            if unreachable:
                return PageSessionState(
                    "system_unresponsive",
                    current_host=host,
                    current_url=url,
                    title=title,
                    retryable=True,
                    reason="page_unresponsive",
                )
        try:
            body_text = str(await page.locator("body").inner_text(timeout=self.config.check_timeout_seconds * 1000))
        except Exception:
            body_text = ""

        combined = f"{title}\n{body_text}"[:20_000]
        elapsed = time.monotonic() - started
        if elapsed >= self.config.check_timeout_seconds and not combined:
            return PageSessionState(
                "system_unresponsive",
                current_host=host,
                current_url=url,
                title=title,
                ready_state=ready_state,
                retryable=True,
                reason="check_timeout",
            )
        if _matches_any(combined, _BLOCKED_WORDS):
            return PageSessionState(
                "blocked_or_access_denied",
                current_host=host,
                current_url=url,
                title=title,
                ready_state=ready_state,
                operator_action_required=True,
                reason="blocked_text",
            )
        if _is_microsoft_auth_url(url, host) or is_reauthentication_url(url, expected_action_hosts(action)):
            return await self._classify_microsoft_page(page, action, url, host, title, ready_state, combined)

        expected_hosts = expected_action_hosts(action)
        if expected_hosts and host not in expected_hosts:
            return PageSessionState(
                "wrong_host",
                current_host=host,
                current_url=url,
                title=title,
                ready_state=ready_state,
                retryable=True,
                reason="unexpected_host",
            )
        if ready_state in {"loading", "interactive"} and _matches_any(combined, _LOADING_WORDS):
            return PageSessionState(
                "system_loading",
                current_host=host,
                current_url=url,
                title=title,
                ready_state=ready_state,
                retryable=True,
                reason="loading_signal",
            )
        if authenticated is True:
            return PageSessionState(
                "authenticated_system",
                current_host=host,
                current_url=url,
                title=title,
                ready_state=ready_state,
                reason="authenticated_marker",
            )
        if authenticated is False:
            return PageSessionState(
                "unknown",
                current_host=host,
                current_url=url,
                title=title,
                ready_state=ready_state,
                retryable=True,
                operator_action_required=True,
                reason="auth_marker_missing",
            )
        return PageSessionState(
            "authenticated_system" if host else "unknown",
            current_host=host,
            current_url=url,
            title=title,
            ready_state=ready_state,
            retryable=not bool(host),
            reason="host_matches_expected" if host else "no_host",
        )

    async def _classify_microsoft_page(
        self,
        page: Any,
        action: Any,
        url: str,
        host: str,
        title: str,
        ready_state: str,
        text: str,
    ) -> PageSessionState:
        password_input_visible = False
        try:
            password_input_visible = await page.locator("input[type='password']:visible").count() > 0
        except Exception:
            password_input_visible = False
        if password_input_visible or _matches_any(text, _PASSWORD_WORDS):
            return PageSessionState(
                "microsoft_password_required",
                host,
                url,
                title,
                ready_state,
                operator_action_required=True,
                reason="password_required",
            )
        if _matches_any(text, _MFA_WORDS):
            return PageSessionState(
                "microsoft_mfa_required",
                host,
                url,
                title,
                ready_state,
                operator_action_required=True,
                reason="mfa_required",
            )
        if _matches_any(text, _CONSENT_WORDS):
            return PageSessionState(
                "microsoft_consent_required",
                host,
                url,
                title,
                ready_state,
                operator_action_required=True,
                reason="consent_required",
            )
        if _matches_any(text, _SIGNED_OUT_WORDS):
            return PageSessionState(
                "microsoft_signed_out",
                host,
                url,
                title,
                ready_state,
                operator_action_required=True,
                retryable=True,
                reason="signed_out",
            )
        if _matches_any(text, _PICK_ACCOUNT_WORDS):
            return PageSessionState(
                "microsoft_pick_account",
                host,
                url,
                title,
                ready_state,
                retryable=True,
                reason="pick_account",
            )
        for account_text in configured_saved_account_texts(action):
            if account_text and account_text.casefold() in text.casefold():
                return PageSessionState(
                    "microsoft_pick_account",
                    host,
                    url,
                    title,
                    ready_state,
                    retryable=True,
                    reason="configured_account_visible",
                )
        return PageSessionState(
            "unknown_microsoft_auth",
            host,
            url,
            title,
            ready_state,
            operator_action_required=True,
            retryable=True,
            reason="unknown_microsoft_auth_page",
        )

    async def ensure_authenticated(
        self,
        page: Any,
        action: Any,
        *,
        is_authenticated: Callable[[Any], Awaitable[bool]] | None = None,
        checkpoint: str = "session_check",
    ) -> SessionRecoveryResult:
        recovery_steps: list[dict[str, Any]] = []
        refreshes = 0
        initial_url = str(_metadata(action, "url_inicial", "") or "").strip()
        state = await self.classify(
            page,
            action,
            authenticated=await is_authenticated(page) if is_authenticated is not None else None,
        )
        if state.state == "authenticated_system":
            return SessionRecoveryResult(ok=True, state=state)

        for attempt in range(1, self.config.recovery_attempts + 1):
            step: dict[str, Any] = {
                "checkpoint": checkpoint,
                "attempt": attempt,
                "state_before": state.state,
                "current_host": state.current_host,
                "action": "none",
                "result": "not_attempted",
            }
            if state.state in {"microsoft_pick_account", "microsoft_signed_out", "unknown_microsoft_auth"}:
                step["action"] = "select_saved_microsoft_account"
                selected = await self.click_configured_saved_account(page, action)
                step["result"] = "clicked" if selected else "configured_account_not_visible"
                recovery_steps.append(step)
                if not selected:
                    state.operator_action_required = True
                    state.retryable = True
                    state.reason = "configured_saved_account_not_found"
                    break
                await self._wait_after_recovery(page)
            elif state.state in {
                "microsoft_password_required",
                "microsoft_mfa_required",
                "microsoft_consent_required",
                "blocked_or_access_denied",
            }:
                step["result"] = "manual_intervention_required"
                recovery_steps.append(step)
                break
            elif state.state in {"system_loading", "system_unresponsive", "unknown"} and refreshes < self.config.refresh_attempts:
                step["action"] = "refresh"
                refreshes += 1
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=self.config.check_timeout_seconds * 1000)
                    step["result"] = "refreshed"
                except Exception as exc:
                    step["result"] = "refresh_failed"
                    step["error_type"] = type(exc).__name__
                recovery_steps.append(step)
                await self._wait_after_recovery(page)
            elif state.state == "wrong_host" and initial_url:
                step["action"] = "navigate_initial_url"
                try:
                    await page.goto(initial_url, wait_until="domcontentloaded", timeout=self.config.check_timeout_seconds * 1000)
                    step["result"] = "navigated"
                except Exception as exc:
                    step["result"] = "navigation_failed"
                    step["error_type"] = type(exc).__name__
                recovery_steps.append(step)
                await self._wait_after_recovery(page)
            else:
                recovery_steps.append(step)
                break

            state = await self.classify(
                page,
                action,
                authenticated=await is_authenticated(page) if is_authenticated is not None else None,
            )
            if state.state == "authenticated_system":
                return SessionRecoveryResult(
                    ok=True,
                    state=state,
                    recovery_attempts=attempt,
                    recovery_steps=recovery_steps,
                    recovery_attempted=True,
                )
            if attempt < self.config.recovery_attempts:
                await asyncio.sleep(self.config.recovery_backoff_seconds)

        return SessionRecoveryResult(
            ok=False,
            state=state,
            recovery_attempts=len(recovery_steps),
            recovery_steps=recovery_steps,
            retryable=bool(state.retryable),
            operator_action_required=bool(state.operator_action_required),
            recovery_attempted=bool(recovery_steps),
        )

    async def click_configured_saved_account(self, page: Any, action: Any) -> bool:
        texts = configured_saved_account_texts(action)
        if not texts:
            return False
        selector = str(_metadata(action, "microsoft_saved_account_selector", "") or "").strip()
        for text in texts:
            if selector:
                try:
                    locator = page.locator(selector).filter(has_text=re.compile(re.escape(text), re.I)).first
                    if await locator.count() > 0 and await locator.is_visible():
                        await locator.click(timeout=self.config.check_timeout_seconds * 1000)
                        return True
                except Exception:
                    pass
            try:
                locator = page.get_by_text(text, exact=False).first
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.click(timeout=self.config.check_timeout_seconds * 1000)
                    return True
            except Exception:
                continue
        return False

    async def _wait_after_recovery(self, page: Any) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self.config.check_timeout_seconds * 1000)
        except Exception:
            pass
        try:
            await page.wait_for_timeout(750)
        except Exception:
            await asyncio.sleep(0.75)


def session_failure_message(state: str, reason: str = "") -> str:
    if state in {"microsoft_password_required", "microsoft_mfa_required", "microsoft_consent_required"}:
        return "Não consegui continuar porque a Microsoft solicitou senha ou MFA."
    if state in {"microsoft_signed_out", "unknown"} and "auth_marker_missing" in reason:
        return "Não consegui executar a ação porque o sistema pediu login manual novamente."
    if state == "microsoft_pick_account" and "configured_saved_account_not_found" in reason:
        return "Não consegui continuar porque a conta salva configurada não apareceu na tela da Microsoft."
    if state in {"system_loading", "system_unresponsive"}:
        return "Não consegui concluir porque o sistema ficou sem resposta mesmo após atualizar a página."
    if state == "blocked_or_access_denied":
        return "Não consegui continuar porque o acesso ao sistema foi bloqueado ou negado."
    if state == "wrong_host":
        return "Não consegui executar a ação porque a página do sistema esperado não está disponível."
    return "Não consegui executar a ação porque o sistema pediu login manual novamente."
