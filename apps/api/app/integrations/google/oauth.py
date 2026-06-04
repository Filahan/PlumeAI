"""Generic Google OAuth: handshake + encrypted token storage, parameterised by tool key.

Client credentials (OAuth client_id + client_secret) are read from the DB-backed
`tool_credentials["google"]` slot (set via the Tools UI). No env vars involved.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.models import Settings as SettingsRow
from app.errors import ProviderError, ToolNotConfigured
from app.services.tool_credentials import get_credentials

log = structlog.get_logger("app.integrations.google.oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass
class GoogleCreds:
    access_token: str
    refresh_token: str
    expires_at: int  # unix ms — 60s safety margin baked in
    scope: str
    token_type: str

    def to_blob(self) -> str:
        return json.dumps(
            {
                "accessToken": self.access_token,
                "refreshToken": self.refresh_token,
                "expiresAt": self.expires_at,
                "scope": self.scope,
                "tokenType": self.token_type,
            },
            separators=(",", ":"),
        )

    @staticmethod
    def from_blob(raw: str) -> "GoogleCreds":
        d = json.loads(raw)
        return GoogleCreds(
            access_token=d["accessToken"],
            refresh_token=d["refreshToken"],
            expires_at=int(d["expiresAt"]),
            scope=d.get("scope", ""),
            token_type=d.get("tokenType", "Bearer"),
        )


async def _require_app_credentials(session: AsyncSession) -> tuple[str, str]:
    """Fetch the Google OAuth client_id + client_secret from DB. Raises if missing."""
    creds = await get_credentials(session, "google")
    if not creds:
        raise ToolNotConfigured(
            "Google credentials are not configured. Open any Google tool's card in "
            "Settings → Tools and save your OAuth client ID and secret."
        )
    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")
    if not client_id or not client_secret:
        raise ToolNotConfigured(
            "Google credentials are incomplete (client_id or client_secret missing)."
        )
    return client_id, client_secret


async def build_auth_url(
    session: AsyncSession, scopes: str, state: str, redirect_uri: str
) -> str:
    client_id, _ = await _require_app_credentials(session)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",  # force refresh_token issuance
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def _post_token(form: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            TOKEN_URL,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    body = r.json()
    if not r.is_success:
        msg = body.get("error_description") or body.get("error") or f"HTTP {r.status_code}"
        raise ProviderError(f"Google token endpoint: {msg}")
    return body


async def exchange_code(
    session: AsyncSession, code: str, redirect_uri: str
) -> GoogleCreds:
    client_id, client_secret = await _require_app_credentials(session)
    body = await _post_token(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    if "refresh_token" not in body:
        raise ProviderError(
            "Google did not return a refresh_token. Revoke the app in your Google account "
            "and retry — 'prompt=consent' should force it."
        )
    return GoogleCreds(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=int(time.time() * 1000) + (int(body["expires_in"]) - 60) * 1000,
        scope=body.get("scope", ""),
        token_type=body.get("token_type", "Bearer"),
    )


async def _refresh(session: AsyncSession, refresh_token: str) -> dict[str, Any]:
    client_id, client_secret = await _require_app_credentials(session)
    return await _post_token(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )


async def _get_row(session: AsyncSession) -> SettingsRow | None:
    return (
        await session.execute(select(SettingsRow).where(SettingsRow.id == 1))
    ).scalar_one_or_none()


async def load_creds(session: AsyncSession, tool_key: str) -> GoogleCreds | None:
    row = await _get_row(session)
    if row is None:
        return None
    blob = (row.tools or {}).get(tool_key)
    if not blob or not blob.get("ciphertext") or not blob.get("iv"):
        return None
    try:
        return GoogleCreds.from_blob(decrypt(blob["iv"], blob["ciphertext"]))
    except Exception:  # noqa: BLE001
        log.warning("google_creds_decrypt_failed", tool_key=tool_key, exc_info=True)
        return None


async def save_creds(session: AsyncSession, tool_key: str, creds: GoogleCreds) -> None:
    row = await _get_row(session)
    if row is None:
        return
    enc = encrypt(creds.to_blob())
    tools = dict(row.tools or {})
    tools[tool_key] = {"ciphertext": enc["ct"], "iv": enc["iv"]}
    row.tools = tools


async def clear_creds(session: AsyncSession, tool_key: str) -> None:
    row = await _get_row(session)
    if row is None:
        return
    tools = dict(row.tools or {})
    tools.pop(tool_key, None)
    row.tools = tools


async def get_valid_access_token(session: AsyncSession, tool_key: str) -> str:
    """Returns a fresh access_token, refreshing + persisting if expired."""
    creds = await load_creds(session, tool_key)
    if creds is None:
        raise ToolNotConfigured(f"{tool_key} is not connected.")

    if int(time.time() * 1000) < creds.expires_at:
        return creds.access_token

    refreshed = await _refresh(session, creds.refresh_token)
    creds.access_token = refreshed["access_token"]
    creds.expires_at = int(time.time() * 1000) + (int(refreshed["expires_in"]) - 60) * 1000
    creds.token_type = refreshed.get("token_type", creds.token_type)
    await save_creds(session, tool_key, creds)
    return creds.access_token
