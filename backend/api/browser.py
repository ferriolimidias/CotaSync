"""Configuracao e saude dos providers de navegador."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.services.browser_providers import (
    BrowserProviderError,
    configured_browser_mode,
    desktop_browser_health,
    save_browser_mode,
)
from backend.services.auth import require_admin


router = APIRouter(prefix="/api/browser", tags=["browser"])


class BrowserModeRequest(BaseModel):
    browser_mode: str


async def _status() -> dict[str, Any]:
    desktop = await desktop_browser_health()
    return {
        "browser_mode": configured_browser_mode(),
        "desktop_browser": desktop,
    }


@router.get("/status")
async def browser_status() -> dict[str, Any]:
    return {"status": "ok", "browser": await _status()}

@router.put("/config")
async def update_browser_config(
    payload: BrowserModeRequest,
    request: Request,
    _admin=Depends(require_admin),
) -> dict[str, Any]:
    del request, _admin
    try:
        save_browser_mode(payload.browser_mode)
    except BrowserProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", "browser": await _status()}
