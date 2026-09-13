"""Discord tool functions: send/list_messages/list_channels/list_guilds.

Auth is via a single bot token stored encrypted in DB (`tool_credentials["discord"]`)
and entered through the Tools UI. The bot must be invited to each server the user
wants to interact with — that is a one-time manual step from the Discord Developer
Portal.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolNotConfigured
from app.integrations.base import CredentialField, Integration
from app.services.tool_credentials import get_credentials
from app.tools.base import TIMEOUT_SECONDS, ActionDisplayMeta, ToolResult, cap

DISCORD_BASE = "https://discord.com/api/v10"

# ─── Setup guide + catalog metadata (ported from apps/web/src/lib/tools/registry-client.ts) ──

DISCORD_SETUP: dict[str, Any] = {
    "intro": (
        "Discord uses a bot token. Create a bot once in the Discord Developer Portal "
        "and paste the token above."
    ),
    "steps": [
        {
            "title": "Create a Discord application",
            "description": 'Pick a name (e.g. "PlumeAI bot").',
            "link": {
                "label": "Open Discord Developer Portal",
                "url": "https://discord.com/developers/applications",
            },
        },
        {
            "title": "Enable the Bot and copy its token",
            "description": (
                'In the "Bot" tab, click "Reset Token" and copy the value — it is shown '
                "only once. Paste it into the Credentials section above."
            ),
        },
        {
            "title": "Invite the bot to your server",
            "description": (
                'OAuth2 → URL Generator → scope "bot" + permissions (Send Messages, Read '
                "Message History). Open the generated URL and pick the server."
            ),
        },
    ],
    "note": (
        "Privileges: Send Messages, Read Message History. The bot can only see channels "
        "you grant it access to."
    ),
}

DISCORD_ACTION_META: dict[str, ActionDisplayMeta] = {
    "discord_list_guilds": ActionDisplayMeta(
        label="List servers",
        output_description="Servers (guilds) the bot has been invited to, with id and name.",
    ),
    "discord_list_channels": ActionDisplayMeta(
        label="List channels",
        output_description="Channels in the server with id, name, and type.",
    ),
    "discord_list_messages": ActionDisplayMeta(
        label="Read messages",
        output_description="Recent messages with author, content, and timestamp.",
    ),
    "discord_send_message": ActionDisplayMeta(
        label="Send a message",
        output_description="Confirmation with the sent message id.",
    ),
}

# ─── OpenAI function-calling schemas ──────────────────────────────────────────────────

DISCORD_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "discord_list_guilds",
            "description": (
                "List all Discord servers (guilds) the bot has been invited to. "
                "Returns id and name for each. Call this first to discover where the bot lives."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_list_channels",
            "description": (
                "List text/voice/forum channels in a Discord server. Returns id, name, type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "string", "description": "Server (guild) id."},
                },
                "required": ["guild_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_list_messages",
            "description": (
                "Read recent messages from a Discord channel. Returns author + content + "
                "timestamp for each, most recent first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "Channel id."},
                    "limit": {
                        "type": "number",
                        "description": "Max messages to return (1-100, default 25).",
                    },
                },
                "required": ["channel_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discord_send_message",
            "description": "Post a plain-text message in a Discord channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "Channel id."},
                    "content": {"type": "string", "description": "Message text (max 2000 chars)."},
                },
                "required": ["channel_id", "content"],
                "additionalProperties": False,
            },
        },
    },
]


# ─── helpers ──────────────────────────────────────────────────────────────────────────


async def _bot_token(session: AsyncSession) -> str:
    creds = await get_credentials(session, "discord")
    token = (creds or {}).get("bot_token")
    if not token:
        raise ToolNotConfigured(
            "Discord is not configured. Open the Discord card in Settings → Tools and "
            "save your bot token."
        )
    return token


async def _discord_fetch(
    session: AsyncSession,
    path: str,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    token = await _bot_token(session)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        return await client.request(
            method=method,
            url=f"{DISCORD_BASE}{path}",
            headers={"Authorization": f"Bot {token}"},
            json=json_body,
            params=params,
        )


_CHANNEL_TYPE_LABELS = {
    0: "text",
    2: "voice",
    4: "category",
    5: "announcement",
    10: "announcement-thread",
    11: "public-thread",
    12: "private-thread",
    13: "stage",
    15: "forum",
    16: "media",
}


def _channel_type_label(t: int | None) -> str:
    return _CHANNEL_TYPE_LABELS.get(t or -1, f"type-{t}")


# ─── tool implementations ────────────────────────────────────────────────────────────


async def _discord_list_guilds(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    r = await _discord_fetch(session, "/users/@me/guilds")
    if not r.is_success:
        return ToolResult(ok=False, content=f"discord_list_guilds HTTP {r.status_code}: {cap(r.text)}")
    guilds = r.json()
    if not guilds:
        return ToolResult(ok=True, content="The bot is not in any server. Invite it first.")
    lines = [f"{i}. [{g.get('id')}] {g.get('name')}" for i, g in enumerate(guilds, 1)]
    return ToolResult(ok=True, content=cap("\n".join(lines)))


async def _discord_list_channels(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    guild_id = args.get("guild_id")
    if not isinstance(guild_id, str):
        return ToolResult(ok=False, content='discord_list_channels requires "guild_id".')
    r = await _discord_fetch(session, f"/guilds/{guild_id}/channels")
    if not r.is_success:
        return ToolResult(ok=False, content=f"discord_list_channels HTTP {r.status_code}: {cap(r.text)}")
    channels = r.json()
    if not channels:
        return ToolResult(ok=True, content="No channels in this guild.")
    lines = [
        f"{i}. [{c.get('id')}] {c.get('name')} ({_channel_type_label(c.get('type'))})"
        for i, c in enumerate(channels, 1)
    ]
    return ToolResult(ok=True, content=cap("\n".join(lines)))


async def _discord_list_messages(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    channel_id = args.get("channel_id")
    if not isinstance(channel_id, str):
        return ToolResult(ok=False, content='discord_list_messages requires "channel_id".')
    raw_limit = args.get("limit", 25)
    limit = max(1, min(int(raw_limit) if isinstance(raw_limit, (int, float)) else 25, 100))
    r = await _discord_fetch(session, f"/channels/{channel_id}/messages", params={"limit": limit})
    if not r.is_success:
        return ToolResult(ok=False, content=f"discord_list_messages HTTP {r.status_code}: {cap(r.text)}")
    messages = r.json()
    if not messages:
        return ToolResult(ok=True, content="No messages in this channel.")
    lines: list[str] = []
    for i, m in enumerate(messages, 1):
        author = (m.get("author") or {}).get("username") or "unknown"
        ts = m.get("timestamp", "")
        content = (m.get("content") or "").strip() or "(empty)"
        lines.append(f"{i}. {author} @ {ts}\n   {content}")
    return ToolResult(ok=True, content=cap("\n\n".join(lines)))


async def _discord_send_message(args: dict[str, Any], session: AsyncSession) -> ToolResult:
    channel_id = args.get("channel_id")
    content = args.get("content")
    if not (isinstance(channel_id, str) and isinstance(content, str)):
        return ToolResult(ok=False, content='discord_send_message requires "channel_id" and "content".')
    if not content.strip():
        return ToolResult(ok=False, content="Message content is empty.")
    r = await _discord_fetch(
        session, f"/channels/{channel_id}/messages", "POST", {"content": content[:2000]}
    )
    if not r.is_success:
        return ToolResult(ok=False, content=f"discord_send_message HTTP {r.status_code}: {cap(r.text)}")
    return ToolResult(ok=True, content=f"Sent. id={r.json().get('id')}")


_DISPATCH = {
    "discord_list_guilds": _discord_list_guilds,
    "discord_list_channels": _discord_list_channels,
    "discord_list_messages": _discord_list_messages,
    "discord_send_message": _discord_send_message,
}


# ─── Integration object ──────────────────────────────────────────────────────────────


class DiscordIntegration(Integration):
    name = "discord"
    label = "Discord"
    description = "Send messages, read messages, and list channels in Discord servers."
    setup_url = ""  # No OAuth — credentials are entered in the Tools UI.
    schemas = DISCORD_SCHEMAS

    logo_url = "https://cdn.simpleicons.org/discord"
    connect_mode = "config"
    setup = DISCORD_SETUP
    action_meta = DISCORD_ACTION_META

    credentials_namespace = "discord"
    credentials_fields = [
        CredentialField(
            name="bot_token",
            label="Bot Token",
            secret=True,
            placeholder="MTAxxx.Gxxxx.xxxxx",
        ),
    ]

    # Permissions bitmask requested in the invite URL (matches what the 4 tools need).
    INVITE_PERMISSIONS = (
        1 << 10  # VIEW_CHANNEL
        | 1 << 11  # SEND_MESSAGES
        | 1 << 16  # READ_MESSAGE_HISTORY
    )

    async def is_configured(self, session: AsyncSession) -> bool:
        creds = await get_credentials(session, "discord")
        return bool(creds and creds.get("bot_token"))

    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult:
        fn = _DISPATCH.get(function_name)
        if fn is None:
            return ToolResult(ok=False, content=f"Unknown discord function: {function_name}")
        try:
            return await fn(args, session)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content=f"Error: {exc}")

    async def fetch_meta(self, session: AsyncSession) -> dict[str, str | None]:
        """Return `{bot_name, application_id, invite_url}` for the configured bot.

        Used by the Tools UI to render the "Invite bot to a server" button without
        the user having to leave PlumeAI for the Discord Developer Portal.
        """
        empty: dict[str, str | None] = {
            "bot_name": None,
            "application_id": None,
            "invite_url": None,
        }
        if not await self.is_configured(session):
            return empty
        try:
            r = await _discord_fetch(session, "/applications/@me")
        except Exception:  # noqa: BLE001
            return empty
        if not r.is_success:
            return empty
        app = r.json()
        app_id = str(app.get("id") or "")
        if not app_id:
            return empty
        return {
            "bot_name": app.get("name"),
            "application_id": app_id,
            "invite_url": (
                "https://discord.com/api/oauth2/authorize"
                f"?client_id={app_id}&scope=bot&permissions={self.INVITE_PERMISSIONS}"
            ),
        }


discord_integration = DiscordIntegration()
