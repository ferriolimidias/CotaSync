"""Construcao segura de URLs publicas para o DevTools do Browserless."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def public_devtools_url(websocket_debugger_url: str, public_base_url: str) -> str:
    """Troca o host CDP interno pelo endpoint publico do Browserless."""

    websocket = urlsplit(str(websocket_debugger_url or "").strip())
    public = urlsplit(str(public_base_url or "").strip().rstrip("/"))
    if websocket.scheme not in {"ws", "wss"}:
        raise ValueError("URL WebSocket do DevTools invalida.")
    if not websocket.path.startswith("/devtools/page/"):
        raise ValueError("URL WebSocket nao aponta para uma pagina do DevTools.")
    if public.scheme not in {"http", "https"} or not public.hostname:
        raise ValueError("URL publica do Browserless invalida.")

    public_path = public.path.rstrip("/")
    inspector_path = f"{public_path}/devtools/inspector.html"
    websocket_path = f"{public_path}{websocket.path}"
    query_name = "wss" if public.scheme == "https" else "ws"
    query_value = f"{public.netloc}{websocket_path}"
    return urlunsplit(
        (public.scheme, public.netloc, inspector_path, f"{query_name}={query_value}", "")
    )


def public_devtools_host(devtools_url: str) -> str:
    """Retorna somente o hostname publico, sem credenciais, path ou query."""

    return urlsplit(str(devtools_url or "")).hostname or ""
