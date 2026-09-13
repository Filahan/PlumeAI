"""Shared fixtures for the automation-document test suite (pure, no DB)."""

from __future__ import annotations

import copy

import pytest

from app.services.documents import ActionMeta

# The example automation document from the automation-builder plan (Task 2, Phase 1).
EXAMPLE_DOCUMENT: dict = {
    "name": "Morning digest from my boss",
    "description": "Summarize unread emails from Dana and post the summary to Slack.",
    "model": {"provider": "openai", "model": "gpt-4o-mini"},
    "trigger": {
        "type": "schedule",
        "settings": {"mode": "cron", "cron": "0 8 * * 1-5", "timezone": "Europe/Paris"},
    },
    "steps": [
        {
            "id": "step_k3f9a",
            "name": "Find unread emails from Dana",
            "type": "action",
            "settings": {
                "integration": "gmail",
                "action": "gmail_search",
                "input": {
                    "query": {
                        "kind": "ai",
                        "value": "Unread emails from dana@acme.com since yesterday",
                    },
                    "max_results": {"kind": "literal", "value": 20},
                },
            },
            "retry": {"max_attempts": 3, "backoff_seconds": 10},
            "timeout_seconds": 120,
            "valid": True,
        },
        {
            "id": "step_p2m7c",
            "name": "Summarize the emails",
            "type": "ai",
            "settings": {
                "instructions": "Emails: {{step_k3f9a.output}}. Write a 5-bullet summary.",
                "tools": ["gmail_get"],
                "output": {
                    "mode": "json",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "urgent": {"type": "boolean"},
                        },
                        "required": ["summary", "urgent"],
                    },
                },
            },
            "valid": True,
        },
        {
            "id": "step_q8d1e",
            "name": "Only continue if there was something",
            "type": "filter",
            "settings": {
                "mode": "rules",
                "rules": {
                    "combinator": "and",
                    "conditions": [
                        {
                            "left": {"kind": "ref", "value": "{{step_k3f9a.output.count}}"},
                            "op": "gt",
                            "right": {"kind": "literal", "value": 0},
                        }
                    ],
                },
            },
            "valid": True,
        },
        {
            "id": "step_z5r2b",
            "name": "Post to Slack",
            "type": "action",
            "settings": {
                "integration": "slack",
                "action": "slack_send_message",
                "input": {
                    "channel": {"kind": "literal", "value": "#me"},
                    "text": {"kind": "ref", "value": "{{step_p2m7c.output.summary}}"},
                },
            },
            "valid": True,
        },
    ],
}


_DEFAULT_ACTIONS: dict[str, ActionMeta] = {
    "gmail_search": ActionMeta(
        name="gmail_search",
        integration="gmail",
        label="Search Gmail",
        description="Search for emails matching a query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    ),
    "slack_send_message": ActionMeta(
        name="slack_send_message",
        integration="slack",
        label="Send Slack message",
        description="Post a message to a channel.",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["channel", "text"],
        },
    ),
}


class StubCatalog:
    """A tiny in-memory `ActionCatalog` implementation for tests."""

    def __init__(
        self,
        actions: dict[str, ActionMeta] | None = None,
        connected: set[str] | None = None,
    ) -> None:
        self._actions = _DEFAULT_ACTIONS if actions is None else actions
        self._connected = {"gmail", "slack"} if connected is None else connected

    def find_action(self, name: str) -> ActionMeta | None:
        return self._actions.get(name)

    def is_connected(self, integration: str) -> bool:
        return integration in self._connected


@pytest.fixture
def catalog() -> StubCatalog:
    return StubCatalog()


@pytest.fixture
def example_document_json() -> dict:
    return copy.deepcopy(EXAMPLE_DOCUMENT)
