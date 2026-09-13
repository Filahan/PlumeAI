"""Slack catalog metadata: the setup guide, per-action display metadata, and the
OpenAI function-calling schemas. Split out of `tools.py` to keep that module about
behavior (HTTP calls + formatting) rather than data.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import ActionDisplayMeta


SLACK_SETUP: dict[str, Any] = {
    "intro": (
        "Slack uses a bot token. Create a Slack app once, install it to your workspace, "
        "and paste the Bot User OAuth Token above."
    ),
    "steps": [
        {
            "title": "Create a Slack app",
            "description": (
                'Choose "From scratch", name it (e.g. "PlumeAI"), and pick your workspace.'
            ),
            "link": {"label": "Open api.slack.com/apps", "url": "https://api.slack.com/apps"},
        },
        {
            "title": "Add the bot token scopes",
            "description": (
                "OAuth & Permissions → Scopes → Bot Token Scopes. Add: chat:write, "
                "channels:read, groups:read, channels:history, groups:history, users:read."
            ),
        },
        {
            "title": "Install to Workspace and copy the token",
            "description": (
                'Click "Install to Workspace", approve, then copy the Bot User OAuth Token '
                "(starts with xoxb-) into the Credentials section above."
            ),
        },
        {
            "title": "Invite the bot to your channels",
            "description": (
                "In Slack, run `/invite @YourBot` in every channel it should post in or read "
                "from. Without the invite, Slack answers not_in_channel."
            ),
        },
    ],
    "note": (
        "Private channels are invisible to the bot until you invite it, even with the "
        "groups:read and groups:history scopes."
    ),
}

SLACK_ACTION_META: dict[str, ActionDisplayMeta] = {
    "slack_list_channels": ActionDisplayMeta(
        label="List channels",
        output_description=(
            "Channels visible to the bot, with id, name, privacy, member count, and topic."
        ),
        output_schema={
            "type": "object",
            "properties": {
                "count": {"type": "number"},
                "channels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "is_private": {"type": "boolean"},
                            "num_members": {"type": "number"},
                            "topic": {"type": "string"},
                        },
                    },
                },
            },
        },
    ),
    "slack_send_message": ActionDisplayMeta(
        label="Send a message",
        output_description="The channel id and the message timestamp (ts), plus a permalink.",
        output_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "ts": {"type": "string"},
                "permalink": {"type": "string"},
            },
        },
    ),
    "slack_read_messages": ActionDisplayMeta(
        label="Read messages",
        output_description=(
            "Recent messages, oldest first, with ts, author id, author name, and text."
        ),
        output_schema={
            "type": "object",
            "properties": {
                "count": {"type": "number"},
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ts": {"type": "string"},
                            "user": {"type": "string"},
                            "user_name": {"type": "string"},
                            "text": {"type": "string"},
                            "thread_ts": {"type": "string"},
                        },
                    },
                },
            },
        },
    ),
}

# ─── OpenAI function-calling schemas ─────────────────────────────────────────────────

SLACK_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "slack_list_channels",
            "description": (
                "List Slack channels the bot can see. Returns id, name, privacy, member "
                "count and topic for each. Call this first to turn a channel name into an id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "types": {
                        "type": "string",
                        "enum": ["public", "private", "all"],
                        "description": "Which channels to list (default all).",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Max channels to return (1-200, default 100).",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slack_send_message",
            "description": (
                "Post a message to a Slack channel. `channel` accepts a channel id "
                '(C0123456789) or a name with a leading hash ("#general"). Pass `thread_ts` '
                "to reply inside an existing thread. The bot must be a member of the channel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": 'Channel id or "#name".'},
                    "text": {
                        "type": "string",
                        "description": "Message text (Slack mrkdwn is supported).",
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "Timestamp of the parent message, to reply in its thread.",
                    },
                },
                "required": ["channel", "text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slack_read_messages",
            "description": (
                "Read recent messages from a Slack channel, oldest first. `channel` accepts "
                'a channel id or "#name". Author ids are resolved to display names when the '
                "users:read scope is granted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": 'Channel id or "#name".'},
                    "limit": {
                        "type": "number",
                        "description": "Max messages to return (1-100, default 20).",
                    },
                    "oldest": {
                        "type": "string",
                        "description": (
                            "Only messages at or after this time. ISO timestamp "
                            "(2026-06-04T14:00:00Z) or a Slack ts."
                        ),
                    },
                },
                "required": ["channel"],
                "additionalProperties": False,
            },
        },
    },
]

