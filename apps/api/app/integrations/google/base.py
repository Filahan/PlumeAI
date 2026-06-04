"""Base class for any Google OAuth-based integration (Gmail, Drive, Calendar, …).

Subclasses declare `tool_key`, `scopes`, `api_base_url`, `schemas`, and a `_dispatch`
mapping. OAuth handshake, encrypted-token storage, refresh, and refresh-on-401 fetch
are all implemented once here.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolNotConfigured
from app.integrations.base import CredentialField, Integration
from app.integrations.google.oauth import (
    build_auth_url,
    exchange_code,
    get_valid_access_token,
    load_creds,
    save_creds,
)
from app.tools.base import TIMEOUT_SECONDS, ToolResult

ToolFn = Callable[["GoogleOAuthIntegration", dict[str, Any], AsyncSession], Awaitable[ToolResult]]


class GoogleOAuthIntegration(Integration):
    """Concrete base: handles the Google OAuth handshake + authed fetch + dispatch."""

    # All Google integrations share a single OAuth callback URL — the user only has to
    # register ONE redirect URI in Google Cloud Console, and any future Google API
    # (Calendar, Sheets, …) plugs in for free. The integration name travels through the
    # OAuth `state` param so the callback knows which integration is being authorized.
    callback_path: ClassVar[str] = "/api/tools/google/oauth/callback"

    # App-level credentials (set once by the operator via the Tools UI), shared by all
    # Google integrations.
    credentials_namespace: ClassVar[str | None] = "google"
    credentials_fields: ClassVar[list[CredentialField]] = [
        CredentialField(
            name="client_id",
            label="OAuth Client ID",
            secret=False,
            placeholder="123-abc.apps.googleusercontent.com",
        ),
        CredentialField(
            name="client_secret",
            label="OAuth Client Secret",
            secret=True,
            placeholder="GOCSPX-...",
        ),
    ]

    # Per-integration configuration. Subclasses MUST set these.
    tool_key: ClassVar[str]
    scopes: ClassVar[str]
    api_base_url: ClassVar[str]

    @property
    @abstractmethod
    def _dispatch(self) -> dict[str, ToolFn]:
        """Map of function_name → bound method that implements it."""
        ...

    # ─── Integration contract ───

    async def is_configured(self, session: AsyncSession) -> bool:
        return (await load_creds(session, self.tool_key)) is not None

    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult:
        fn = self._dispatch.get(function_name)
        if fn is None:
            return ToolResult(ok=False, content=f"Unknown {self.name} function: {function_name}")
        try:
            return await fn(self, args, session)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content=f"Error: {exc}")

    # ─── OAuth hooks ───

    async def oauth_start_url(
        self, session: AsyncSession, state: str, redirect_uri: str
    ) -> str | None:
        return await build_auth_url(session, self.scopes, state, redirect_uri)

    async def oauth_exchange_and_save(
        self, code: str, redirect_uri: str, session: AsyncSession
    ) -> None:
        creds = await exchange_code(session, code, redirect_uri)
        await save_creds(session, self.tool_key, creds)

    # ─── HTTP helper for subclasses ───

    async def authed_fetch(
        self,
        session: AsyncSession,
        path: str,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Authenticated request to the Google API. Retries once on 401 after a forced
        token refresh."""
        url = path if path.startswith("http") else f"{self.api_base_url}{path}"
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            token = await get_valid_access_token(session, self.tool_key)
            r = await client.request(
                method=method,
                url=url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
                params=params,
            )
            if r.status_code != 401:
                return r

            # 401 → force refresh (zero out expiresAt) then retry once.
            creds = await load_creds(session, self.tool_key)
            if creds is None:
                raise ToolNotConfigured(f"{self.tool_key} credentials disappeared mid-request.")
            creds.expires_at = 0
            await save_creds(session, self.tool_key, creds)

            token = await get_valid_access_token(session, self.tool_key)
            return await client.request(
                method=method,
                url=url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
                params=params,
            )
