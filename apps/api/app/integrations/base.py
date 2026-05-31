"""Integration protocol: any third-party tool that needs OAuth/config implements this."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.base import ToolResult


class Integration(Protocol):
    """A first-party integration (Gmail, future: Calendar, Drive, ...).

    Each integration owns its OAuth flow, its credential storage, and its tool functions.
    The registry exposes only `is_configured()` integrations to the agent's toolset.
    """

    name: str  # 'gmail' — matches the @mention and the function-name prefix (`gmail_*`)
    label: str  # 'Gmail'
    description: str  # one-line description, used in setup UI
    setup_url: str  # browser-facing URL that starts OAuth (e.g. '/api/tools/gmail/oauth/start')
    schemas: list[dict[str, Any]]  # OpenAI function-calling schemas

    async def is_configured(self, session: AsyncSession) -> bool: ...

    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult: ...
