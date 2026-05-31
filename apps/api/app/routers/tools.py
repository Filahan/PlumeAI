"""Tool / integration routes: Gmail OAuth handshake + disconnect.

Disconnect is also exposed via `/settings/tools/{name}/disconnect` (Phase 2) — that one
is the canonical UI handler; this module focuses on OAuth.
"""

from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.config import get_settings
from app.db.base import get_session
from app.errors import BadRequest, ToolNotConfigured
from app.integrations.gmail.oauth import (
    build_auth_url,
    exchange_code,
    save_creds,
)

router = APIRouter(prefix="/tools", tags=["tools"])
log = structlog.get_logger("app.tools.oauth")

DBSession = Annotated[AsyncSession, Depends(get_session)]

STATE_COOKIE = "gmail_oauth_state"
STATE_TTL_SECONDS = 600


def _redirect_uri() -> str:
    """Callback URI sent to Google's OAuth screen.

    Anchored on the public frontend URL (FRONTEND_URL env var, defaults to
    http://localhost:3000) — NEVER on the inbound request's Host header. The Host header
    may be `api:8000` (Docker-internal) or `localhost:8000` (direct API access), neither
    of which is what's registered in Google Cloud Console. Always sending the same URL
    means there's exactly ONE entry to whitelist there.
    """
    return f"{get_settings().frontend_url}/api/tools/gmail/oauth/callback"


def _tools_redirect(status: str, message: str | None = None) -> RedirectResponse:
    """Bounce the user back to the /tools page with status flags for the UI to read."""
    target = f"/tools?tool=gmail&status={quote(status)}"
    if message:
        target += f"&message={quote(message)}"
    return RedirectResponse(target, status_code=302)


@router.get("/gmail/oauth/start")
async def gmail_oauth_start(request: Request, user: CurrentUser) -> RedirectResponse:
    redirect_uri = _redirect_uri()
    log.info("gmail_oauth_start", redirect_uri=redirect_uri)
    try:
        state = secrets.token_urlsafe(24)
        auth_url = build_auth_url(state, redirect_uri)
    except ToolNotConfigured:
        # Friendly path when env vars are missing: bounce to /tools with a flag.
        return _tools_redirect("required", "GOOGLE_OAUTH_CLIENT_ID / SECRET missing")

    response = RedirectResponse(auth_url, status_code=302)
    response.set_cookie(
        key=STATE_COOKIE,
        value=state,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=STATE_TTL_SECONDS,
        path="/",
    )
    return response


@router.get("/gmail/oauth/callback")
async def gmail_oauth_callback(
    request: Request,
    user: CurrentUser,
    session: DBSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    expected_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
) -> RedirectResponse:
    response: RedirectResponse | None = None
    if error:
        response = _tools_redirect("error", error)
    elif not code or not state or not expected_state or state != expected_state:
        response = _tools_redirect("error", "invalid_state")
    else:
        try:
            creds = await exchange_code(code, _redirect_uri())
            await save_creds(session, creds)
            response = _tools_redirect("connected")
        except Exception as exc:  # noqa: BLE001
            log.warning("gmail_oauth_callback_failed", exc_info=True)
            response = _tools_redirect("error", str(exc)[:200])

    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.post("/{name}/disconnect")
async def disconnect_tool_route(
    name: str, user: CurrentUser, session: DBSession
) -> dict[str, str]:
    """Convenience alias for the `/settings/tools/{name}/disconnect` route."""
    from app.services.settings import disconnect_tool as _disconnect

    if not name:
        raise BadRequest("tool name required")
    await _disconnect(session, name)
    return {"status": "ok"}
