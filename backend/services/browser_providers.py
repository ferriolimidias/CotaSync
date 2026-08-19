"""Provider CDP para o navegador desktop persistente."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit, urlunsplit

import requests

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


BrowserMode = Literal["desktop_browser"]
VALID_BROWSER_MODES: tuple[BrowserMode, ...] = ("desktop_browser",)
_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "data" / "browser_config.json"


class BrowserProviderError(RuntimeError):
    """Falha operacional segura ao selecionar ou conectar um provider."""


@dataclass(frozen=True)
class BrowserConnection:
    browser: Browser
    context: BrowserContext
    page: Page


def normalize_browser_mode(value: Any) -> BrowserMode:
    mode = str(value or "").strip().lower()
    if mode in {"", "desktop_browser"}:
        return "desktop_browser"
    raise BrowserProviderError("Modo de navegador invalido. Use desktop_browser.")


def configured_browser_mode() -> BrowserMode:
    """Retorna a escolha da UI quando persistida; caso contrario usa o ambiente."""

    if _CONFIG_PATH.is_file():
        try:
            payload = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("browser_mode"):
                return normalize_browser_mode(payload["browser_mode"])
        except (OSError, json.JSONDecodeError, BrowserProviderError):
            pass
    raw = os.getenv("COTASYNC_BROWSER_MODE", "desktop_browser")
    try:
        return normalize_browser_mode(raw)
    except BrowserProviderError:
        return "desktop_browser"


def save_browser_mode(mode: Any) -> BrowserMode:
    selected = normalize_browser_mode(mode)
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=_CONFIG_PATH.parent, delete=False) as tmp:
            json.dump({"browser_mode": selected}, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, _CONFIG_PATH)
        tmp_path = None
    except OSError as exc:
        raise BrowserProviderError("Nao foi possivel salvar o modo de navegador.") from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return selected


def desktop_cdp_url() -> str:
    return os.getenv(
        "DESKTOP_BROWSER_CDP_URL",
        "http://cotasync_test_desktop_browser:9222",
    ).strip().rstrip("/")


def desktop_view_url() -> str:
    return os.getenv(
        "DESKTOP_BROWSER_VIEW_URL",
        "http://127.0.0.1:3200/vnc.html?autoconnect=1&resize=scale",
    ).strip()


def desktop_profile_dir() -> str:
    return os.getenv("DESKTOP_BROWSER_PROFILE_DIR", "/data/profile").strip() or "/data/profile"


def _safe_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _resolved_desktop_endpoint() -> tuple[str, str]:
    """Resolve o hostname Docker para IP, aceito pela protecao de Host do Chromium."""

    raw = desktop_cdp_url()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        raise BrowserProviderError("DESKTOP_BROWSER_CDP_URL invalida.")
    try:
        address = socket.gethostbyname(parsed.hostname)
    except OSError as exc:
        raise BrowserProviderError("Navegador desktop nao esta em execucao.") from exc
    port = parsed.port or (443 if parsed.scheme in {"https", "wss"} else 80)
    http_scheme = "https" if parsed.scheme in {"https", "wss"} else "http"
    base = urlunsplit((http_scheme, f"{address}:{port}", parsed.path.rstrip("/"), "", ""))
    return base.rstrip("/"), address


def _desktop_version(timeout: float = 3.0) -> dict[str, Any]:
    base, address = _resolved_desktop_endpoint()
    parsed = urlsplit(base)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    response = requests.get(
        f"{base}/json/version",
        headers={"Host": f"{address}:{port}"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("webSocketDebuggerUrl"):
        raise BrowserProviderError("CDP do navegador desktop respondeu sem WebSocket.")
    return payload


async def desktop_browser_health() -> dict[str, Any]:
    running = False
    reachable = False
    product = ""
    error = ""
    try:
        base, _ = await asyncio.to_thread(_resolved_desktop_endpoint)
        parsed = urlsplit(base)
        with socket.create_connection((parsed.hostname or "", parsed.port or 9222), timeout=1.5):
            running = True
        version = await asyncio.to_thread(_desktop_version, 2.5)
        reachable = True
        product = str(version.get("Browser") or "")
    except Exception as exc:
        error = type(exc).__name__
    return {
        "running": running,
        "cdp_reachable": reachable,
        "cdp_url": _safe_url(desktop_cdp_url()),
        "view_url": desktop_view_url(),
        "profile_dir": desktop_profile_dir(),
        "browser_product": product,
        "error": error,
    }


class BrowserProvider:
    mode: BrowserMode
    close_browser_on_session_end = True

    async def connect(self, playwright: Playwright, session_id: str) -> BrowserConnection:
        raise NotImplementedError

    def live_url(self, target_id: str) -> str:
        raise NotImplementedError


class DesktopBrowserProvider(BrowserProvider):
    mode: BrowserMode = "desktop_browser"
    close_browser_on_session_end = False

    async def connect(self, playwright: Playwright, session_id: str) -> BrowserConnection:
        del session_id
        try:
            version = await asyncio.to_thread(_desktop_version, 5.0)
            endpoint = str(version["webSocketDebuggerUrl"])
            browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=10_000)
        except BrowserProviderError:
            raise
        except Exception as exc:
            raise BrowserProviderError("Nao foi possivel conectar ao navegador desktop via CDP.") from exc
        context = browser.contexts[0] if browser.contexts else await browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        pages = [page for page in context.pages if not page.is_closed()]
        page = pages[-1] if pages else await context.new_page()
        for candidate in reversed(pages):
            try:
                if await candidate.evaluate("document.visibilityState === 'visible'"):
                    page = candidate
                    break
            except Exception:
                continue
        return BrowserConnection(browser=browser, context=context, page=page)

    def live_url(self, target_id: str) -> str:
        del target_id
        return desktop_view_url()


def browser_provider(mode: BrowserMode | str | None = None) -> BrowserProvider:
    normalize_browser_mode(mode) if mode is not None else configured_browser_mode()
    return DesktopBrowserProvider()
