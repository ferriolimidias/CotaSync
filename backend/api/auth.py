from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from backend.services.auth import authenticate, clear_auth_cookies, require_user, set_auth_cookies

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _user_payload(username: str, role: str) -> dict[str, str]:
    return {"username": username, "role": role}


@router.post("/login")
async def login(payload: LoginRequest, response: Response) -> dict[str, object]:
    user = authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    csrf_token = set_auth_cookies(response, user)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "user": _user_payload(user.username, user.role), "csrf_token": csrf_token}


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    user = require_user(request)
    return {"status": "ok", "user": _user_payload(user.username, user.role)}
