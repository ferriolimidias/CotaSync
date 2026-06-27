"""Selecao e validacao da pagina usada por uma acao no navegador desktop."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit


REAUTHENTICATION_MESSAGE = "Nao consegui executar a acao porque a sessao precisa ser autenticada novamente."
WRONG_PAGE_MESSAGE = "Nao consegui executar a acao porque a pagina do sistema esperado nao esta disponivel."

_LOGIN_HOST_SUFFIXES = (
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "login.windows.net",
    "m365.cloud.microsoft",
)
_LOGIN_PATH_MARKERS = ("login", "signin", "sign-in", "oauth", "authorize", "auth")


class ActionPageError(RuntimeError):
    """Falha operacional de pagina, sem expor dados de autenticacao."""

    def __init__(self, message: str, *, reason: str, current_url: str = "") -> None:
        super().__init__(message)
        self.diagnostics = {
            "reason": reason,
            "current_host": url_host(current_url),
        }


def _metadata(action: Any, key: str, default: Any = None) -> Any:
    if isinstance(action, dict):
        return action.get(key, default)
    return getattr(action, key, default)


def url_host(url: Any) -> str:
    try:
        return (urlsplit(str(url or "").strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _redirect_uri_host(login_url: Any) -> str:
    try:
        parsed = urlsplit(str(login_url or "").strip())
        redirect_uri = parse_qs(parsed.query).get("redirect_uri", [""])[0]
        return url_host(redirect_uri)
    except (ValueError, IndexError):
        return ""


def _normalized_business_host(value: Any) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    if not raw:
        return ""
    parsed_host = url_host(raw)
    host = parsed_host or raw
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in _LOGIN_HOST_SUFFIXES):
        return ""
    if "/" in host or "?" in host:
        return ""
    return host


def expected_action_hosts(action: Any) -> set[str]:
    """Retorna somente hosts de negocio aceitos para a acao."""

    hosts = {
        url_host(_metadata(action, "url_inicial", "")),
        _redirect_uri_host(_metadata(action, "external_login_url", "")),
        _normalized_business_host(_metadata(action, "expected_system_host", "")),
    }

    # A configuracao corrente so complementa a acao quando representa o mesmo
    # sistema externo. O host do provedor de identidade nunca e aceito como
    # pagina final da acao.
    action_system = str(_metadata(action, "external_system_name", "") or "").strip()
    if action_system:
        try:
            from backend.services.external_systems import load_current_external_system

            current = load_current_external_system()
            if str(current.get("external_system_name") or "").strip() == action_system:
                hosts.add(_redirect_uri_host(current.get("external_login_url")))
                hosts.add(_normalized_business_host(current.get("expected_system_host")))
        except Exception:
            pass
    return {host for host in hosts if host}


def is_reauthentication_url(url: Any, expected_hosts: set[str] | None = None) -> bool:
    raw = str(url or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in _LOGIN_HOST_SUFFIXES):
        return True
    path = (parsed.path or "").casefold()
    if host and host in (expected_hosts or set()):
        return any(marker in path for marker in _LOGIN_PATH_MARKERS)
    return False


def validate_action_page_url(action: Any, url: Any) -> None:
    raw = str(url or "").strip()
    hosts = expected_action_hosts(action)
    if is_reauthentication_url(raw, hosts):
        raise ActionPageError(REAUTHENTICATION_MESSAGE, reason="reauthentication_required", current_url=raw)
    host = url_host(raw)
    if not host or host not in hosts:
        raise ActionPageError(WRONG_PAGE_MESSAGE, reason="unexpected_page_host", current_url=raw)


async def select_desktop_page_for_action(action: Any, context: Any, preferred_page: Any = None) -> Any:
    """Escolhe uma pagina do sistema alvo e navega quando nenhuma ja corresponde."""

    pages = [page for page in context.pages if not page.is_closed()]
    initial_url = str(_metadata(action, "url_inicial", "") or "").strip()
    initial_host = url_host(initial_url)
    expected_hosts = expected_action_hosts(action)

    def candidates_for(hosts: set[str]) -> list[Any]:
        return [page for page in pages if url_host(getattr(page, "url", "")) in hosts]

    matching = candidates_for({initial_host}) if initial_host else []
    if not matching:
        matching = candidates_for(expected_hosts)
    page = (
        preferred_page
        if preferred_page is not None and preferred_page in matching
        else (matching[-1] if matching else None)
    )
    if page is None and preferred_page is not None and not preferred_page.is_closed():
        page = preferred_page
    if page is None:
        page = pages[-1] if pages else await context.new_page()

    if initial_url and url_host(getattr(page, "url", "")) not in expected_hosts:
        await page.goto(initial_url, wait_until="domcontentloaded", timeout=15_000)
    else:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            # Paginas ja carregadas podem nao emitir um novo evento de load.
            pass
    validate_action_page_url(action, page.url)
    return page
