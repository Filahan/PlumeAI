"""Tool / integration routes: OAuth handshake + disconnect.

Two callback patterns coexist:

1. **Provider-unified callback** (preferred for Google): integrations expose a
   `callback_path` class attribute (e.g. `/api/tools/google/oauth/callback`). All
   Google integrations share that one URL, so the user registers exactly one redirect
   URI in Google Cloud Console — Drive, Gmail, and any future Google API plug in for
   free. The integration name travels through the OAuth `state` param.

2. **Per-integration fallback**: `/api/tools/{name}/oauth/callback` — used when an
   integration does not override `callback_path`.
"""

from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.config import get_settings
from app.db.base import get_session
from app.errors import BadRequest, NotFound, ToolNotConfigured
from app.integrations.base import Integration
from app.integrations.registry import find_integration_by_name

router = APIRouter(prefix="/tools", tags=["tools"])
log = structlog.get_logger("app.tools.oauth")

DBSession = Annotated[AsyncSession, Depends(get_session)]

STATE_TTL_SECONDS = 600


def _callback_path(integ: Integration) -> str:
    """Provider-unified path if the integration overrides it, else per-integration."""
    override = getattr(integ.__class__, "callback_path", None)
    return override or f"/api/tools/{integ.name}/oauth/callback"


def _redirect_uri(integ: Integration) -> str:
    """Full callback URL anchored on FRONTEND_URL (NEVER on the inbound Host header)."""
    return f"{get_settings().frontend_url}{_callback_path(integ)}"


def _state_cookie_name(integ: Integration) -> str:
    """One cookie per provider — derived from the callback path so all Google
    integrations share the same cookie (no need to track per-integration state)."""
    # Take the second-to-last path segment (e.g. ".../google/oauth/callback" → "google").
    parts = _callback_path(integ).strip("/").split("/")
    # ["api", "tools", "google", "oauth", "callback"] → "google"
    return f"{parts[-3]}_oauth_state" if len(parts) >= 3 else "oauth_state"


def _tools_redirect(name: str, status: str, message: str | None = None) -> RedirectResponse:
    """Bounce the user back to the /tools page with status flags for the UI to read."""
    target = f"/tools?tool={quote(name)}&status={quote(status)}"
    if message:
        target += f"&message={quote(message)}"
    return RedirectResponse(target, status_code=302)


# ─── /start (per integration) ────────────────────────────────────────────────────────


@router.get("/{name}/oauth/start")
async def oauth_start(
    name: str, request: Request, user: CurrentUser, session: DBSession
) -> RedirectResponse:
    integ = find_integration_by_name(name)
    if integ is None:
        raise NotFound(f"Integration {name} not found.")

    redirect_uri = _redirect_uri(integ)
    log.info("oauth_start", integration=name, redirect_uri=redirect_uri)

    random_token = secrets.token_urlsafe(24)
    # Encode the integration name in `state` so a unified callback can dispatch.
    state = f"{name}:{random_token}"
    try:
        auth_url = await integ.oauth_start_url(session, state, redirect_uri)
    except ToolNotConfigured as exc:
        return _tools_redirect(name, "required", str(exc)[:200])

    if auth_url is None:
        raise BadRequest(f"{name} does not support OAuth.")

    response = RedirectResponse(auth_url, status_code=302)
    response.set_cookie(
        key=_state_cookie_name(integ),
        value=random_token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=STATE_TTL_SECONDS,
        path="/",
    )
    return response


# ─── Unified Google callback ─────────────────────────────────────────────────────────


@router.get("/google/oauth/callback")
async def google_oauth_callback(
    request: Request,
    user: CurrentUser,
    session: DBSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Single callback shared by every `GoogleOAuthIntegration` subclass. The
    integration name is parsed from the `state` param (`<name>:<random>`)."""
    name, _, random_from_state = (state or "").partition(":")
    expected_random = request.cookies.get("google_oauth_state")
    integ = find_integration_by_name(name) if name else None

    response: RedirectResponse
    if error:
        response = _tools_redirect(name or "google", "error", error)
    elif (
        not code
        or not random_from_state
        or not expected_random
        or random_from_state != expected_random
        or integ is None
    ):
        response = _tools_redirect(name or "google", "error", "invalid_state")
    else:
        try:
            await integ.oauth_exchange_and_save(code, _redirect_uri(integ), session)
            response = _tools_redirect(name, "connected")
        except Exception as exc:  # noqa: BLE001
            log.warning("google_oauth_callback_failed", integration=name, exc_info=True)
            response = _tools_redirect(name, "error", str(exc)[:200])

    response.delete_cookie("google_oauth_state", path="/")
    return response


# ─── Per-integration fallback callback (non-Google providers) ───────────────────────


@router.get("/{name}/oauth/callback")
async def oauth_callback(
    name: str,
    request: Request,
    user: CurrentUser,
    session: DBSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    integ = find_integration_by_name(name)
    if integ is None:
        raise NotFound(f"Integration {name} not found.")

    cookie_name = _state_cookie_name(integ)
    # Integrations on the unified Google callback should NEVER hit this route; if they
    # do (e.g. stale Google Cloud Console registration), redirect explaining the fix.
    if _callback_path(integ) != f"/api/tools/{name}/oauth/callback":
        return _tools_redirect(
            name,
            "error",
            "redirect_uri_mismatch — register /api/tools/google/oauth/callback in Google Cloud Console",
        )

    expected_random = request.cookies.get(cookie_name)
    _, _, random_from_state = (state or "").partition(":")

    response: RedirectResponse
    if error:
        response = _tools_redirect(name, "error", error)
    elif (
        not code
        or not random_from_state
        or not expected_random
        or random_from_state != expected_random
    ):
        response = _tools_redirect(name, "error", "invalid_state")
    else:
        try:
            await integ.oauth_exchange_and_save(code, _redirect_uri(integ), session)
            response = _tools_redirect(name, "connected")
        except Exception as exc:  # noqa: BLE001
            log.warning("oauth_callback_failed", integration=name, exc_info=True)
            response = _tools_redirect(name, "error", str(exc)[:200])

    response.delete_cookie(cookie_name, path="/")
    return response


# ─── Discord meta — invite URL helper ───────────────────────────────────────────────


@router.get("/discord/meta")
async def discord_meta(
    user: CurrentUser, session: DBSession
) -> dict[str, str | None]:
    """Return `{bot_name, application_id, invite_url}` for the configured bot.

    The frontend renders the invite URL as a 1-click button so the user never has to
    leave PlumeAI to go to the Discord Developer Portal.
    """
    from app.integrations.discord import discord_integration

    return await discord_integration.fetch_meta(session)


# ─── App-level credentials (per provider namespace) ─────────────────────────────────


def _find_credentials_fields(namespace: str) -> list[str] | None:
    """Return the allowed field names for `namespace`, or None if no integration uses it."""
    from app.integrations.registry import INTEGRATIONS

    for integ in INTEGRATIONS:
        if integ.credentials_namespace == namespace and integ.credentials_fields:
            return [f.name for f in integ.credentials_fields]
    return None


@router.put("/credentials/{namespace}")
async def save_tool_credentials(
    namespace: str,
    fields: dict[str, str],
    user: CurrentUser,
    session: DBSession,
) -> dict[str, str]:
    """Persist credentials for `namespace`. Only the fields declared by an integration
    are accepted; unknown fields are silently dropped."""
    from app.services.tool_credentials import save_credentials

    allowed = _find_credentials_fields(namespace)
    if allowed is None:
        raise NotFound(f"No integration uses credentials namespace '{namespace}'.")

    cleaned: dict[str, str] = {}
    for k in allowed:
        v = fields.get(k)
        if v is None:
            raise BadRequest(f"Missing required field: {k}")
        if not isinstance(v, str) or not v.strip():
            raise BadRequest(f"Field {k} cannot be empty.")
        cleaned[k] = v.strip()

    await save_credentials(session, namespace, cleaned)
    return {"status": "ok"}


@router.delete("/credentials/{namespace}")
async def clear_tool_credentials(
    namespace: str, user: CurrentUser, session: DBSession
) -> dict[str, str]:
    from app.services.tool_credentials import clear_credentials

    await clear_credentials(session, namespace)
    return {"status": "ok"}


# ─── Disconnect ──────────────────────────────────────────────────────────────────────


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
