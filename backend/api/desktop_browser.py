"""Acesso publico temporario a visualizacao noVNC do Desktop Browser."""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Header, HTTPException, Query, Response, status

from backend.services.desktop_view_tokens import create_token, validate_token
from backend.services.browser_providers import desktop_view_url


router = APIRouter(prefix="/api/desktop-browser", tags=["desktop-browser"])

_INTERNAL_VIEW_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


def _is_internal_view_host(host: str) -> bool:
    normalized = host.strip().lower().rstrip(".")
    return (
        normalized in _INTERNAL_VIEW_HOSTS
        or normalized.endswith(".local")
        or normalized.startswith("cotasync_")
    )


def _public_view_url(token: str) -> str:
    public_base = os.getenv("COTASYNC_DESKTOP_VIEW_PUBLIC_BASE_URL", "").strip().rstrip("/")
    raw_url = f"{public_base}/vnc.html" if public_base else desktop_view_url()
    parsed = urlsplit(raw_url)
    if _is_internal_view_host(parsed.hostname or ""):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="COTASYNC_DESKTOP_VIEW_PUBLIC_BASE_URL deve apontar para o dominio publico do noVNC.",
        )
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"token": token, "autoconnect": "1", "resize": "scale"})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/vnc.html", urlencode(query), ""))


@router.post("/view-token")
def create_desktop_view_token(response: Response) -> dict[str, object]:
    created = create_token()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return {
        "status": "ok",
        "view_url": _public_view_url(created.token),
        "expires_at": created.expires_at.isoformat(),
        "ttl_seconds": created.ttl_seconds,
    }


@router.get("/validate-view-token", status_code=status.HTTP_200_OK)
def validate_desktop_view_token(
    response: Response,
    token: str | None = Query(default=None),
    x_desktop_view_token: str | None = Header(default=None, alias="X-Desktop-View-Token"),
) -> dict[str, str]:
    # O header permite ao auth_request evitar repetir o segredo na URL dos logs internos.
    candidate = token or x_desktop_view_token
    if not validate_token(candidate):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired view token.")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}
