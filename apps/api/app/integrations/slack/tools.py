"""Slack tool functions: list_channels / send_message / read_messages.

Auth is a single bot token (xoxb-…) stored encrypted in DB (`tool_credentials["slack"]`)
and entered through the Tools UI — the same config-mode pattern Discord uses. The bot
must be invited to every channel it should post in or read from.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import CredentialField, Integration
from app.integrations.slack.client import (
    CHANNEL_TYPES,
    CREDENTIALS_NAMESPACE,
    SlackContext,
    format_ts,
    list_conversations,
    resolve_channel,
    resolve_user_names,
    slack_call,
    slack_context,
    to_slack_ts,
)
from app.integrations.slack.schemas import SLACK_ACTION_META, SLACK_SCHEMAS, SLACK_SETUP
from app.services.tool_credentials import get_credentials
from app.tools.base import ToolResult, cap


def _clamp(raw: Any, default: int, high: int) -> int:
    value = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else default
    return max(1, min(value, high))


# ─── tool implementations ────────────────────────────────────────────────────────────


async def _slack_list_channels(args: dict[str, Any], ctx: SlackContext) -> ToolResult:
    kind = args.get("types") if args.get("types") in CHANNEL_TYPES else "all"
    limit = _clamp(args.get("limit"), 100, 200)
    raw = await list_conversations(ctx, types=CHANNEL_TYPES[str(kind)], limit=limit)

    channels: list[dict[str, Any]] = []
    for c in raw:
        entry: dict[str, Any] = {
            "id": c.get("id"),
            "name": c.get("name"),
            "is_private": bool(c.get("is_private")),
        }
        if isinstance(c.get("num_members"), int):
            entry["num_members"] = c["num_members"]
        topic = ((c.get("topic") or {}).get("value") or "").strip()
        if topic:
            entry["topic"] = topic
        channels.append(entry)

    data = {"channels": channels, "count": len(channels)}
    if not channels:
        return ToolResult(
            ok=True,
            content="No channels are visible to the bot. Invite it with /invite @YourBot.",
            data=data,
        )
    lines = []
    for i, c in enumerate(channels, 1):
        bits = ["private" if c["is_private"] else "public"]
        if "num_members" in c:
            bits.append(f"{c['num_members']} members")
        suffix = f" — {c['topic']}" if c.get("topic") else ""
        lines.append(f"{i}. [{c['id']}] #{c['name']} ({', '.join(bits)}){suffix}")
    return ToolResult(ok=True, content=cap("\n".join(lines)), data=data)


async def _slack_send_message(args: dict[str, Any], ctx: SlackContext) -> ToolResult:
    channel = args.get("channel")
    text = args.get("text")
    if not isinstance(channel, str) or not channel.strip():
        return ToolResult(
            ok=False, content='slack_send_message requires "channel".', retryable=False
        )
    if not isinstance(text, str) or not text.strip():
        return ToolResult(
            ok=False, content='slack_send_message requires non-empty "text".', retryable=False
        )

    channel_id, display = await resolve_channel(ctx, channel)
    body: dict[str, Any] = {"channel": channel_id, "text": text}
    thread_ts = args.get("thread_ts")
    if isinstance(thread_ts, str) and thread_ts.strip():
        body["thread_ts"] = thread_ts.strip()

    payload = await slack_call(
        ctx,
        "chat.postMessage",
        json_body=body,
        error_hints={
            "not_in_channel": (
                f"The bot is not in {display}. In Slack, run `/invite @YourBot` in "
                f"{display} and retry."
            ),
            "channel_not_found": (
                f"Slack could not find {display}. Use slack_list_channels for the id — a "
                "private channel stays invisible until the bot is invited."
            ),
        },
    )
    ts = str(payload.get("ts") or "")
    data: dict[str, Any] = {"channel": str(payload.get("channel") or channel_id), "ts": ts}
    permalink = await _permalink(ctx, data["channel"], ts)
    if permalink:
        data["permalink"] = permalink
    return ToolResult(ok=True, content=f"Sent to {display}. ts={ts}", data=data)


async def _permalink(ctx: SlackContext, channel_id: str, ts: str) -> str | None:
    """Best-effort `chat.getPermalink` — a nice-to-have that must never fail the send."""
    if not (channel_id and ts):
        return None
    try:
        payload = await slack_call(
            ctx, "chat.getPermalink", params={"channel": channel_id, "message_ts": ts}
        )
    except Exception:  # noqa: BLE001
        return None
    link = payload.get("permalink")
    return str(link) if link else None


async def _slack_read_messages(args: dict[str, Any], ctx: SlackContext) -> ToolResult:
    channel = args.get("channel")
    if not isinstance(channel, str) or not channel.strip():
        return ToolResult(
            ok=False, content='slack_read_messages requires "channel".', retryable=False
        )
    limit = _clamp(args.get("limit"), 20, 100)
    channel_id, display = await resolve_channel(ctx, channel)

    params: dict[str, Any] = {"channel": channel_id, "limit": limit}
    oldest = to_slack_ts(args.get("oldest"))
    if oldest:
        # `inclusive` makes the bound mean "at or after", which is what the schema promises.
        params["oldest"] = oldest
        params["inclusive"] = True

    payload = await slack_call(
        ctx,
        "conversations.history",
        params=params,
        error_hints={
            "not_in_channel": (
                f"The bot is not in {display}. In Slack, run `/invite @YourBot` in "
                f"{display} and retry."
            ),
        },
    )

    # Slack returns newest-first; the transcript reads better oldest-first.
    raw = [m for m in (payload.get("messages") or []) if isinstance(m, dict)]
    raw.reverse()

    # One users.info round per distinct author, all in flight together.
    names = await resolve_user_names(ctx, (str(m.get("user") or "") for m in raw))

    messages: list[dict[str, Any]] = []
    for m in raw:
        user = str(m.get("user") or m.get("bot_id") or "")
        entry: dict[str, Any] = {
            "ts": str(m.get("ts") or ""),
            "user": user,
            "text": m.get("text") or "",
        }
        name = names.get(str(m.get("user") or ""))
        if name:
            entry["user_name"] = name
        if m.get("thread_ts"):
            entry["thread_ts"] = str(m["thread_ts"])
        messages.append(entry)

    data = {"messages": messages, "count": len(messages)}
    if not messages:
        return ToolResult(ok=True, content=f"No messages in {display}.", data=data)
    lines = [
        f"[{format_ts(m['ts'])}] {m.get('user_name') or m['user'] or 'unknown'}: "
        f"{(m['text'] or '').strip() or '(no text)'}"
        for m in messages
    ]
    return ToolResult(ok=True, content=cap("\n".join(lines)), data=data)


_DISPATCH = {
    "slack_list_channels": _slack_list_channels,
    "slack_send_message": _slack_send_message,
    "slack_read_messages": _slack_read_messages,
}


# ─── Integration object ──────────────────────────────────────────────────────────────


class SlackIntegration(Integration):
    name = "slack"
    label = "Slack"
    description = "Post messages, read channel history, and list channels in Slack."
    setup_url = ""  # No OAuth — the bot token is entered in the Tools UI.
    schemas = SLACK_SCHEMAS

    logo_url = "https://cdn.simpleicons.org/slack"
    connect_mode = "config"
    setup = SLACK_SETUP
    action_meta = SLACK_ACTION_META

    credentials_namespace = CREDENTIALS_NAMESPACE
    credentials_fields = [
        CredentialField(
            name="bot_token",
            label="Bot token (xoxb-…)",
            secret=True,
            placeholder="xoxb-…",
        ),
    ]

    async def is_configured(self, session: AsyncSession) -> bool:
        creds = await get_credentials(session, CREDENTIALS_NAMESPACE)
        return bool(creds and creds.get("bot_token"))

    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult:
        fn = _DISPATCH.get(function_name)
        if fn is None:
            return ToolResult(
                ok=False, content=f"Unknown slack function: {function_name}", retryable=False
            )
        # `AppError`s (ToolError / ToolNotConfigured) deliberately propagate: `app.tools.
        # registry.execute_tool` maps them to a failed ToolResult *with* the right
        # `retryable` flag, which a blanket except here would throw away.
        return await fn(args, await slack_context(session))


slack_integration = SlackIntegration()
