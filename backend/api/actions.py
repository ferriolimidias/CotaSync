from __future__ import annotations

import logging
import json

from fastapi import APIRouter, HTTPException

from backend.schemas.actions import ActionDetailResponse, ActionsListResponse, ActionsRawResponse
from backend.schemas.runs import ActionRunRequest, ActionRunResponse
from backend.services.action_validation_review import run_validation_review, schedule_validation_review
from backend.services.actions_repository import ActionsRepositoryError, find_action, load_actions_catalog
from backend.services.runs_repository import RunsRepositoryError

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


@router.post("/{action_id}/validate-review", response_model=ActionRunResponse)
async def validate_review_action(action_id: str, payload: ActionRunRequest) -> ActionRunResponse:
    try:
        action = find_action(action_id)
    except ActionsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if action is None:
        logger.info("Tentativa de validar acao inexistente: %s", action_id)
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")

    try:
        if payload.mode == "async":
            run = schedule_validation_review(action, payload)
        else:
            run = await run_validation_review(action, payload)
    except ValueError as exc:
        try:
            detail = json.loads(str(exc))
        except json.JSONDecodeError:
            detail = {"message": str(exc)}
        raise HTTPException(status_code=422, detail=detail) from exc
    except RunsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ActionRunResponse(run=run)
