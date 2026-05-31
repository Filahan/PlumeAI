"""Auth routes — login (password → cookie) and logout (clear cookie)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.auth import (
    CurrentUser,
    check_admin_password,
    clear_session_cookie,
    create_session_token,
    set_session_cookie,
)
from app.errors import Unauthorized

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1)


class SessionResponse(BaseModel):
    user: str


@router.post("/login", response_model=SessionResponse)
async def login(body: LoginRequest, response: Response) -> SessionResponse:
    if not check_admin_password(body.password):
        raise Unauthorized("Invalid password.")
    token = create_session_token()
    set_session_cookie(response, token)
    return SessionResponse(user="admin")


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me", response_model=SessionResponse)
async def me(user: CurrentUser) -> SessionResponse:
    return SessionResponse(user=user)
