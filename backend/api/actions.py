from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.schemas.actions import ActionDetailResponse, ActionsListResponse, ActionsRawResponse
from backend.services.actions_repository import ActionsRepositoryError, find_action, load_actions_catalog

logger = logging.getLogger("cotasync.api.actions")

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("", response_model=ActionsListResponse)
async def list_actions() -> ActionsListResponse:
    try:
        catalog = load_actions_catalog()
    except ActionsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ActionsListResponse(
        count=len(catalog.actions),
        actions=catalog.actions,
        warning=catalog.warning,
    )


@router.get("/raw", response_model=ActionsRawResponse)
async def raw_actions_catalog() -> ActionsRawResponse:
    try:
        catalog = load_actions_catalog()
    except ActionsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ActionsRawResponse(
        exists=catalog.exists,
        count=len(catalog.actions),
        keys=[action.key for action in catalog.actions],
        warning=catalog.warning,
    )


@router.get("/{action_id}", response_model=ActionDetailResponse)
async def get_action(action_id: str) -> ActionDetailResponse:
    try:
        action = find_action(action_id)
    except ActionsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if action is None:
        logger.info("Acao nao encontrada via API: %s", action_id)
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")

    return ActionDetailResponse(action=action)
