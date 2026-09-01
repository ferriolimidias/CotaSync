from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.runs import (
    ActionRunRequest,
    ActionRunResponse,
    RunDetailResponse,
    RunsListResponse,
    RunStatus,
)
from backend.services.action_runner import missing_required_variables, run_action_sync, schedule_finish_action_run, start_action_run
from backend.services.actions_repository import ActionsRepositoryError, find_action
from backend.services.runs_repository import RunsRepositoryError, get_run, list_runs

logger = logging.getLogger("cotasync.api.runs")

actions_run_router = APIRouter(prefix="/api/actions", tags=["runs"])
runs_router = APIRouter(prefix="/api/runs", tags=["runs"])


@actions_run_router.post("/{action_id}/run", response_model=ActionRunResponse)
async def run_action(action_id: str, payload: ActionRunRequest) -> ActionRunResponse:
    try:
        action = find_action(action_id)
    except ActionsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if action is None:
        logger.info("Tentativa de executar acao inexistente: %s", action_id)
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")

    missing = missing_required_variables(action, payload.variables)
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Variaveis obrigatorias ausentes.",
                "missing_variables": missing,
            },
        )

    try:
        if payload.mode == "async":
            run = start_action_run(action, payload)
            schedule_finish_action_run(action, payload, run)
            return ActionRunResponse(run=run)
        run = await run_action_sync(action, payload)
    except RunsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ActionRunResponse(run=run)


@runs_router.get("", response_model=RunsListResponse)
async def get_runs(
    action_id: str | None = Query(default=None),
    status: RunStatus | None = Query(default=None),
    limit: int | None = Query(default=None, ge=0, le=500),
) -> RunsListResponse:
    try:
        runs = list_runs(action_id=action_id, status=status, limit=limit)
    except RunsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunsListResponse(count=len(runs), runs=runs)


@runs_router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run_detail(run_id: str) -> RunDetailResponse:
    try:
        run = get_run(run_id)
    except RunsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if run is None:
        raise HTTPException(status_code=404, detail="Run nao encontrada.")

    return RunDetailResponse(run=run)
