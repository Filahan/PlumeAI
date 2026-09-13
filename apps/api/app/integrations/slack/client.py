"""Thin Slack Web API client: bot-token auth, one `slack_call` entry point, and the
per-action context that carries the resolved token and the id caches.

Kept separate from `tools.py` so the HTTP/error-mapping layer can be tested on its own
and the tool module stays about schemas and formatting.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ToolError, ToolNotConfigured
from app.services.tool_credentials import get_credentials
from app.tools.base import TIMEOUT_SECONDS, with_timeout

log = structlog.get_logger("app.integrations.slack")

SLACK_BASE = "https://slack.com/api"
CREDENTIALS_NAMESPACE = "slack"

# A `ToolError` the automation executor should not spend another attempt on: the request
# itself is wrong (bad token, missing scope, unknown channel), so the next try fails too.
_PERMANENT = {"retryable": False}

# Slack `error` codes that a later attempt could plausibly get past.
_RETRYABLE_ERRORS = {
    "ratelimited",
    "rate_limited",
    "internal_error",
    "service_unavailable",
    "fatal_error",
    "request_timeout",
}

# Human-facing translations for the Slack error codes users actually hit.
_ERROR_MESSAGES: dict[str, str] = {
    "invalid_auth": (
        "Slack rejected the bot token. Re-copy the Bot User OAuth Token (xoxb-…) from "
        "OAuth & Permissions into Settings → Tools → Slack."
    ),
    "token_revoked": "The Slack bot token was revoked. Re-install the app and save the new token.",
    "account_inactive": "The Slack bot's account is deactivated in this workspace.",
    "not_authed": "No Slack bot token was sent with the request.",
    "channel_not_found": (
        "Slack could not find that channel. Use slack_list_channels to get its id, and "
        "remember the bot only sees private channels it was invited to."
    ),
    "not_in_channel": (
        "The bot is not a member of that channel. In Slack, run `/invite @YourBot` in the "
        "channel and retry."
    ),
    "is_archived": "That Slack channel is archived.",
    "msg_too_long": "The message text is too long for Slack (max ~40k characters).",
    "no_text": "Slack needs non-empty message text.",
    "restricted_action": "The workspace settings do not allow the bot to do that.",
    "ratelimited": "Slack rate-limited the request.",
}


def _http_client() -> httpx.AsyncClient:
    """Factory for the HTTP client. Tests replace this to inject an `httpx.MockTransport`."""
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)


async def bot_token(session: AsyncSession) -> str:
    creds = await get_credentials(session, CREDENTIALS_NAMESPACE)
    token = (creds or {}).get("bot_token")
    if not token:
        raise ToolNotConfigured(
            "Slack is not configured. Open the Slack card in Settings → Tools and save "
            "your bot token (xoxb-…)."
        )
    return str(token)


@dataclass
class SlackContext:
    """State shared by every HTTP call one tool action makes.

    The bot token is read (and decrypted) once per action rather than once per request,
    and the two caches mean a channel name or a user id is resolved at most once even
    when an action mentions it repeatedly.
    """

    token: str
    channels: dict[str, str] = field(default_factory=dict)
    users: dict[str, str] = field(default_factory=dict)


async def slack_context(session: AsyncSession) -> SlackContext:
    return SlackContext(token=await bot_token(session))


def _missing_scope_message(payload: dict[str, Any]) -> str:
    needed = payload.get("needed") or "the required scope"
    return (
        f"The Slack bot token is missing a scope ({needed}). Add it under OAuth & "
        "Permissions → Bot Token Scopes, re-install the app, and save the new token."
    )


async def slack_call(
    ctx: SlackContext,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    error_hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """POST to `https://slack.com/api/{method}` and return the parsed `ok: true` payload.

    Slack answers almost every failure with HTTP 200 + `{"ok": false, "error": "..."}`,
    so the error mapping lives here: each known code becomes a `ToolError` with a message
    the automation author can act on, marked non-retryable unless another attempt could
    actually do better. `error_hints` lets a caller override the message for a code it has
    extra context for (e.g. which channel the bot must be invited to).
    """
    headers = {"Authorization": f"Bearer {ctx.token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"

    async with _http_client() as client:
        r = await with_timeout(
            client.post(
                f"{SLACK_BASE}/{method}",
                headers=headers,
                data=None if json_body is not None else _form(params),
                json=json_body,
            )
        )

    if r.status_code == 429:
        retry_after = r.headers.get("retry-after", "30")
        raise ToolError(
            f"Slack rate-limited {method}. Retry after {retry_after}s.",
            extra={"retry_after": _int_or_none(retry_after)},
        )
    if 400 <= r.status_code < 500:
        # Any other 4xx is Slack refusing this exact request (bad method, bad payload);
        # replaying it unchanged would fail the same way.
        raise ToolError(
            f"Slack {method} failed: HTTP {r.status_code} {r.text[:300]}",
            extra=dict(_PERMANENT),
        )
    if not r.is_success:
        raise ToolError(f"Slack {method} failed: HTTP {r.status_code} {r.text[:300]}")

    try:
        payload = r.json()
    except ValueError as exc:
        raise ToolError(f"Slack {method} returned a non-JSON response.") from exc
    if not isinstance(payload, dict):
        raise ToolError(f"Slack {method} returned an unexpected response.")

    if payload.get("ok"):
        return payload

    code = str(payload.get("error") or "unknown_error")
    if code == "missing_scope":
        message = _missing_scope_message(payload)
    elif error_hints and code in error_hints:
        message = error_hints[code]
    else:
        message = _ERROR_MESSAGES.get(code, f"Slack {method} failed: {code}")
    retryable = code in _RETRYABLE_ERRORS
    log.info("slack_api_error", method=method, code=code, retryable=retryable)
    raise ToolError(message, extra=None if retryable else dict(_PERMANENT))


def _int_or_none(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _form(params: dict[str, Any] | None) -> dict[str, str] | None:
    """Slack's form-encoded endpoints want strings; booleans must be "true"/"false"."""
    if not params:
        return None
    out: dict[str, str] = {}
    for k, v in params.items():
        if v is None:
            continue
        out[k] = "true" if v is True else "false" if v is False else str(v)
    return out


# ─── id resolution (cached on the per-action context) ────────────────────────────────

CHANNEL_TYPES = {
    "public": "public_channel",
    "private": "private_channel",
    "all": "public_channel,private_channel",
}

# Slack ids: channels start with C, DMs with D, group DMs with G, then 8+ upper-case
# alphanumerics. Anything else the user typed is treated as a channel *name*.
_CHANNEL_ID_RE = re.compile(r"^[CDG][A-Z0-9]{8,}$")


async def list_conversations(
    ctx: SlackContext, *, types: str, limit: int
) -> list[dict[str, Any]]:
    """`conversations.list`, following `next_cursor` until `limit` channels are collected."""
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(10):  # hard page cap: 10 × 200 channels is plenty
        payload = await slack_call(
            ctx,
            "conversations.list",
            params={
                "types": types,
                "exclude_archived": True,
                "limit": min(200, max(1, limit - len(out))),
                **({"cursor": cursor} if cursor else {}),
            },
        )
        out.extend(c for c in (payload.get("channels") or []) if isinstance(c, dict))
        cursor = ((payload.get("response_metadata") or {}).get("next_cursor")) or None
        if not cursor or len(out) >= limit:
            break
    return out[:limit]


async def resolve_channel(ctx: SlackContext, channel: str) -> tuple[str, str]:
    """Turn a user-supplied channel into `(id, display_name)`.

    An id (`C0123456789`) passes straight through. Anything else — `"#general"` or a bare
    `"general"` — is looked up by name through `conversations.list`, whose result is cached
    on the context so an action that mentions the same channel twice looks it up once.
    """
    raw = channel.strip()
    if _CHANNEL_ID_RE.match(raw):
        return raw, raw
    name = raw.lstrip("#").strip()
    display = f"#{name}"
    if not name:
        raise ToolError("No channel was given.", extra=dict(_PERMANENT))

    key = name.lower()
    if key not in ctx.channels:
        for c in await list_conversations(ctx, types=CHANNEL_TYPES["all"], limit=1000):
            cname = str(c.get("name") or "").lower()
            if cname:
                ctx.channels[cname] = str(c.get("id") or "")
    if key not in ctx.channels:
        raise ToolError(
            f"No channel named {display} is visible to the bot. Check the spelling, and "
            f"for a private channel invite the bot with /invite @YourBot in {display}.",
            extra=dict(_PERMANENT),
        )
    return ctx.channels[key], display


async def resolve_user_names(ctx: SlackContext, user_ids: Iterable[str]) -> dict[str, str]:
    """Best-effort `users.info` for every id not already cached, all in flight at once.

    Display names are a nicety: a workspace that never granted `users:read` still gets its
    messages, just keyed by raw user id.
    """
    todo = [uid for uid in dict.fromkeys(user_ids) if uid and uid not in ctx.users]
    if todo:
        names = await asyncio.gather(*(_fetch_user_name(ctx, uid) for uid in todo))
        ctx.users.update(dict(zip(todo, names, strict=True)))
    return {uid: name for uid, name in ctx.users.items() if name}


async def _fetch_user_name(ctx: SlackContext, user_id: str) -> str:
    try:
        payload = await slack_call(ctx, "users.info", params={"user": user_id})
    except Exception:  # noqa: BLE001 — names must never fail a read
        return ""
    user = payload.get("user") or {}
    profile = user.get("profile") or {}
    name = profile.get("display_name") or profile.get("real_name") or user.get("name") or ""
    return str(name)


def to_slack_ts(value: Any) -> str | None:
    """Accept an ISO timestamp or a Slack ts (`"1712345678.000100"`) → a Slack ts.

    ISO is tried first: `"20260604"` is a date in basic ISO form, not a number of seconds.
    The ts branch then requires the dot Slack always includes, so a typo like `"yesterday"`
    (or a bare `"3"`) is reported instead of silently becoming 1970.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    else:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return f"{dt.timestamp():.6f}"
    if "." in text:
        try:
            return f"{float(text):.6f}"
        except ValueError:
            pass
    raise ToolError(
        f'Could not read "{text}" as a time. Use an ISO timestamp '
        "(2026-06-04T14:00:00Z) or a Slack ts (1712345678.000100).",
        extra=dict(_PERMANENT),
    )


def format_ts(ts: str) -> str:
    """`"1712345678.000100"` → `"2024-04-05 18:14:38 UTC"` (falls back to the raw ts)."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError):
        return ts
