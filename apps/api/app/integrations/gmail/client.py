"""Authed Gmail API client with refresh-on-401 retry."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProviderError, ToolNotConfigured
from app.integrations.gmail.oauth import (
    get_valid_access_token,
    load_creds,
    save_creds,
)
from app.tools.base import TIMEOUT_SECONDS

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"


async def gmail_fetch(
    session: AsyncSession,
    path: str,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """Authenticated request to the Gmail REST API. Retries once on 401 after a forced
    token refresh, mirroring the Node client behavior."""
    url = path if path.startswith("http") else f"{GMAIL_BASE}{path}"

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        token = await get_valid_access_token(session)
        r = await client.request(
            method=method,
            url=url,
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
        )
        if r.status_code != 401:
            return r

        # 401 → force refresh (zero out expiresAt) then retry once.
        creds = await load_creds(session)
        if creds is None:
            raise ToolNotConfigured("Gmail credentials disappeared mid-request.")
        creds.expires_at = 0
        await save_creds(session, creds)

        token = await get_valid_access_token(session)
        r = await client.request(
            method=method,
            url=url,
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
        )
        return r


def ensure_ok(r: httpx.Response, op: str) -> None:
    if not r.is_success:
        # Truncate body for log noise.
        body = r.text[:500]
        raise ProviderError(f"{op} failed (HTTP {r.status_code}): {body}")
