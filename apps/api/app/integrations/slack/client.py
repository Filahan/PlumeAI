"""Thin Slack Web API client: bot-token auth, one `slack_call` entry point, and the
id-resolution caches the tool functions share within a single call.

Kept separate from `tools.py` so the HTTP/error-mapping layer can be tested on its own
and the tool module stays about schemas and formatting.
"""

from __future__ import annotations

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


def _missing_scope_message(payload: dict[str, Any]) -> str:
    needed = payload.get("needed") or "the required scope"
    return (
        f"The Slack bot token is missing a scope ({needed}). Add it under OAuth & "
        "Permissions → Bot Token Scopes, re-install the app, and save the new token."
    )


async def slack_call(
    session: AsyncSession,
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
    token = await bot_token(session)
    headers = {"Authorization": f"Bearer {token}"}
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


# ─── id resolution (per-call caches, passed in by the tool functions) ────────────────

CHANNEL_TYPES = {
    "public": "public_channel",
    "private": "private_channel",
    "all": "public_channel,private_channel",
}


async def list_conversations(
    session: AsyncSession, *, types: str, limit: int
) -> list[dict[str, Any]]:
    """`conversations.list`, following `next_cursor` until `limit` channels are collected."""
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(10):  # hard page cap: 10 × 200 channels is plenty
        payload = await slack_call(
            session,
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


async def resolve_channel(
    session: AsyncSession, channel: str, cache: dict[str, str]
) -> tuple[str, str]:
    """Turn a user-supplied channel (`"#general"` or an id) into `(id, display_name)`.

    `cache` is a per-call dict so one tool call resolving several names hits
    `conversations.list` once.
    """
    raw = channel.strip()
    if not raw.startswith("#"):
        return raw, raw
    name = raw.lstrip("#").lower()
    if name in cache:
        return cache[name], raw
    for c in await list_conversations(
        session, types=CHANNEL_TYPES["all"], limit=1000
    ):
        cname = str(c.get("name") or "").lower()
        if cname:
            cache[cname] = str(c.get("id") or "")
    if name not in cache:
        raise ToolError(
            f"No channel named {raw} is visible to the bot. Check the spelling, and for a "
            f"private channel invite the bot with /invite @YourBot in {raw}.",
            extra=dict(_PERMANENT),
        )
    return cache[name], raw


async def user_display_name(
    session: AsyncSession, user_id: str, cache: dict[str, str]
) -> str | None:
    """Best-effort `users.info` lookup — a missing `users:read` scope must not fail a read."""
    if not user_id:
        return None
    if user_id in cache:
        return cache[user_id] or None
    try:
        payload = await slack_call(session, "users.info", params={"user": user_id})
    except Exception:  # noqa: BLE001 — names are a nicety, never a hard failure
        cache[user_id] = ""
        return None
    user = payload.get("user") or {}
    profile = user.get("profile") or {}
    name = profile.get("display_name") or profile.get("real_name") or user.get("name") or ""
    cache[user_id] = str(name)
    return str(name) or None


def to_slack_ts(value: Any) -> str | None:
    """Accept a Slack ts (`"1712345678.000100"`) or an ISO timestamp and return a Slack ts."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(float(text))  # already a ts / epoch seconds
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(
            f'Could not read "{text}" as a time. Use an ISO timestamp '
            "(2026-06-04T14:00:00Z) or a Slack ts.",
            extra=dict(_PERMANENT),
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.timestamp():.6f}"


def format_ts(ts: str) -> str:
    """`"1712345678.000100"` → `"2024-04-05 18:14:38 UTC"` (falls back to the raw ts)."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError):
        return ts
