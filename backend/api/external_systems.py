"""API da configuracao JSON do sistema externo atual."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.external_systems import (
    ExternalSystemConfigError,
    load_current_external_system,
    save_current_external_system,
)


router = APIRouter(prefix="/api/external-systems", tags=["external-systems"])


class ExternalSystemRequest(BaseModel):
    external_system_name: str = ""
    external_login_url: str = ""
    validation: str = ""
    auth_success_text: str = ""
    auth_success_selector: str = ""
    access_profile_name: str = ""
    access_profile_email_or_identifier: str = ""
    microsoft_saved_account_selector: str = ""
    microsoft_saved_account_text: str = ""


def _safe_call(operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        config = (
            save_current_external_system(payload or {})
            if operation == "save"
            else load_current_external_system()
        )
    except ExternalSystemConfigError as exc:
        raise HTTPException(status_code=422 if operation == "save" else 500, detail=str(exc)) from exc
    return {"status": "ok", "external_system": config}


@router.get("/current")
async def get_current_external_system() -> dict[str, Any]:
    return _safe_call("load")


@router.put("/current")
async def put_current_external_system(payload: ExternalSystemRequest) -> dict[str, Any]:
    return _safe_call("save", payload.model_dump())
