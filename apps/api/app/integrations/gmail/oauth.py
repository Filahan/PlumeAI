"""Google OAuth handshake + token storage for Gmail.

Tokens (access + refresh + expiry) are encrypted as a single JSON blob and stored in
`settings.tools.gmail = {ciphertext, iv}` — the same shape the legacy Node code used,
so existing connections continue to work.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import decrypt, encrypt
from app.db.models import Settings as SettingsRow
from app.errors import ProviderError, ToolNotConfigured

log = structlog.get_logger("app.integrations.gmail.oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOOL_KEY = "gmail"

# "modify" subsumes read + label + trash + mark-read; we add send + labels for clarity.
GMAIL_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.labels",
    ]
)


@dataclass
class GmailCreds:
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
    def from_blob(raw: str) -> "GmailCreds":
        d = json.loads(raw)
        return GmailCreds(
            access_token=d["accessToken"],
            refresh_token=d["refreshToken"],
            expires_at=int(d["expiresAt"]),
            scope=d.get("scope", ""),
            token_type=d.get("tokenType", "Bearer"),
        )


def _require_env() -> tuple[str, str]:
    settings = get_settings()
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise ToolNotConfigured(
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be set in the API "
            "environment to enable Gmail."
        )
    return settings.google_oauth_client_id, settings.google_oauth_client_secret


def build_auth_url(state: str, redirect_uri: str) -> str:
    client_id, _ = _require_env()
    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_SCOPES,
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


async def exchange_code(code: str, redirect_uri: str) -> GmailCreds:
    client_id, client_secret = _require_env()
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
    return GmailCreds(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=int(time.time() * 1000) + (int(body["expires_in"]) - 60) * 1000,
        scope=body.get("scope", ""),
        token_type=body.get("token_type", "Bearer"),
    )


async def _refresh(refresh_token: str) -> dict[str, Any]:
    client_id, client_secret = _require_env()
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


async def load_creds(session: AsyncSession) -> GmailCreds | None:
    row = await _get_row(session)
    if row is None:
        return None
    blob = (row.tools or {}).get(TOOL_KEY)
    if not blob or not blob.get("ciphertext") or not blob.get("iv"):
        return None
    try:
        return GmailCreds.from_blob(decrypt(blob["iv"], blob["ciphertext"]))
    except Exception:  # noqa: BLE001
        log.warning("gmail_creds_decrypt_failed", exc_info=True)
        return None


async def save_creds(session: AsyncSession, creds: GmailCreds) -> None:
    row = await _get_row(session)
    if row is None:
        # Shouldn't happen — settings is created in get_or_create on first access.
        return
    enc = encrypt(creds.to_blob())
    tools = dict(row.tools or {})
    tools[TOOL_KEY] = {"ciphertext": enc["ct"], "iv": enc["iv"]}
    row.tools = tools


async def clear_creds(session: AsyncSession) -> None:
    row = await _get_row(session)
    if row is None:
        return
    tools = dict(row.tools or {})
    tools.pop(TOOL_KEY, None)
    row.tools = tools


async def get_valid_access_token(session: AsyncSession) -> str:
    """Returns a fresh access_token, refreshing + persisting if expired."""
    creds = await load_creds(session)
    if creds is None:
        raise ToolNotConfigured("Gmail is not connected.")

    if int(time.time() * 1000) < creds.expires_at:
        return creds.access_token

    refreshed = await _refresh(creds.refresh_token)
    creds.access_token = refreshed["access_token"]
    creds.expires_at = int(time.time() * 1000) + (int(refreshed["expires_in"]) - 60) * 1000
    creds.token_type = refreshed.get("token_type", creds.token_type)
    await save_creds(session, creds)
    return creds.access_token
