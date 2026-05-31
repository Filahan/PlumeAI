"""Settings routes — GET (decrypted view), PUT (encrypts), disconnect-tool."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.base import get_session
from app.schemas.settings import SettingsPayload
from app.services import settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])

DBSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=SettingsPayload, response_model_by_alias=True)
async def get_settings(user: CurrentUser, session: DBSession) -> SettingsPayload:
    return await settings_service.get_settings_for_client(session)


@router.put("", response_model=SettingsPayload, response_model_by_alias=True)
async def update_settings(
    payload: SettingsPayload, user: CurrentUser, session: DBSession
) -> SettingsPayload:
    await settings_service.save_settings(session, payload)
    # Round-trip: return the freshly-stored state (no secrets leak since plaintext came
    # in from the client and we just echo it).
    return await settings_service.get_settings_for_client(session)


@router.post("/tools/{name}/disconnect")
async def disconnect_tool_route(
    name: str, user: CurrentUser, session: DBSession
) -> dict[str, str]:
    await settings_service.disconnect_tool(session, name)
    return {"status": "ok"}
