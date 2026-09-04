from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.services.actions_repository import ActionsRepositoryError, find_action
from backend.services.clients_repository import (
    ClientsRepositoryError,
    client_template_csv,
    create_client,
    deactivate_client,
    delete_client,
    import_clients_csv,
    list_clients,
    list_groups,
    update_client,
    validate_clients_for_action,
)

router = APIRouter(prefix="/api/clients", tags=["clients"])
groups_router = APIRouter(prefix="/api/client-groups", tags=["clients"])


class ClientPayload(BaseModel):
    name: str
    group: str = "Lista Principal"
    active: bool = True
    notes: str = ""
    variables: dict[str, Any] = Field(default_factory=dict)


class ClientImportPayload(BaseModel):
    csv_text: str


@router.get("")
async def list_clients_endpoint(group: str | None = None, include_inactive: bool = True) -> dict[str, Any]:
    try:
        clients = list_clients(group=group, include_inactive=include_inactive)
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "count": len(clients), "clients": clients}


@router.post("")
async def create_client_endpoint(payload: ClientPayload) -> dict[str, Any]:
    try:
        client = create_client(payload.model_dump())
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", "client": client}


@router.put("/{client_id}")
async def update_client_endpoint(client_id: str, payload: ClientPayload) -> dict[str, Any]:
    try:
        client = update_client(client_id, payload.model_dump())
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "client": client}


@router.post("/{client_id}/deactivate")
async def deactivate_client_endpoint(client_id: str) -> dict[str, Any]:
    try:
        client = deactivate_client(client_id)
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "client": client}


@router.delete("/{client_id}")
async def delete_client_endpoint(client_id: str) -> dict[str, Any]:
    try:
        delete_client(client_id)
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/import-csv")
async def import_clients_csv_endpoint(payload: ClientImportPayload) -> dict[str, Any]:
    try:
        result = import_clients_csv(payload.csv_text)
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "ok", **result}


@router.get("/template.csv")
async def client_template_csv_endpoint() -> Response:
    return Response(
        content=client_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="clientes_cotasync_modelo.csv"'},
    )


@router.get("/validate-for-action/{action_id}")
async def validate_clients_for_action_endpoint(
    action_id: str,
    client_group: str | None = None,
    list_id: str | None = None,
    client_ids: str | None = None,
) -> dict[str, Any]:
    try:
        action = find_action(action_id)
    except ActionsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if action is None:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    ids = [item.strip() for item in str(client_ids or "").split(",") if item.strip()]
    try:
        result = validate_clients_for_action(action, client_group=client_group, list_id=list_id, client_ids=ids)
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", **result}


@groups_router.get("")
async def list_client_groups_endpoint() -> dict[str, Any]:
    try:
        groups = list_groups()
    except ClientsRepositoryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "count": len(groups), "groups": groups}
