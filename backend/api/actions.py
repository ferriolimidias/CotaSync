from __future__ import annotations

import logging
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas.actions import ActionDetailResponse, ActionsListResponse, ActionsRawResponse
from backend.schemas.runs import ActionRunRequest, ActionRunResponse
from backend.services.action_validation_review import run_validation_review, schedule_validation_review
from backend.services.actions_repository import ActionsRepositoryError, find_action, load_actions_catalog
from backend.services.demo_session import DemoSessionError, demo_session_manager
from backend.services.result_selection import build_extraction_contract, save_visual_extraction_contract
from backend.services.runs_repository import RunsRepositoryError

logger = logging.getLogger("cotasync.api.actions")

router = APIRouter(prefix="/api/actions", tags=["actions"])


class ResultSelectionRequest(BaseModel):
    session_id: str = ""
    target_name: str = ""
    screen_label: str = ""


class ResultSelectionConfirmRequest(BaseModel):
    target_name: str
    screen_label: str = ""
    selection_type: str = ""
    candidate: dict[str, object] = Field(default_factory=dict)
    return_format: str = "somente o valor"


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


@router.post("/{action_id}/result-selection/start")
async def start_result_selection(action_id: str, payload: ResultSelectionRequest) -> dict[str, object]:
    action = find_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    if not payload.session_id:
        raise HTTPException(status_code=422, detail="session_id obrigatorio para selecao visual.")
    try:
        result = await demo_session_manager.start_result_selection(payload.session_id)
    except DemoSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "selection": result}


@router.post("/{action_id}/result-selection/capture")
async def capture_result_selection(action_id: str, payload: ResultSelectionRequest) -> dict[str, object]:
    action = find_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    if not payload.session_id:
        raise HTTPException(status_code=422, detail="session_id obrigatorio para captura visual.")
    try:
        result = await demo_session_manager.capture_result_selection(
            payload.session_id,
            target_name=payload.target_name,
            screen_label=payload.screen_label,
        )
    except DemoSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.post("/{action_id}/result-selection/confirm")
async def confirm_result_selection(action_id: str, payload: ResultSelectionConfirmRequest) -> dict[str, object]:
    action = find_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    contract = build_extraction_contract(
        target_name=payload.target_name,
        screen_label=payload.screen_label,
        candidate=payload.candidate,
        selection_type=payload.selection_type,
        return_format=payload.return_format,
    )
    try:
        saved = save_visual_extraction_contract(action.key, contract)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "extraction_review": contract, "reviewed_overlay": saved.get("reviewed_overlay", {})}


@router.post("/{action_id}/extraction-candidates")
async def extraction_candidates(action_id: str, payload: ResultSelectionRequest) -> dict[str, object]:
    action = find_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    if not payload.session_id:
        raise HTTPException(status_code=422, detail="session_id obrigatorio para detectar candidatos.")
    try:
        result = await demo_session_manager.detect_result_candidates(
            payload.session_id,
            target_name=payload.target_name,
            screen_label=payload.screen_label,
        )
    except DemoSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", **result}
