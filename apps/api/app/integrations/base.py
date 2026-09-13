"""Abstract base class every first-party integration (Gmail, Drive, …) inherits from."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.base import ToolResult


@dataclass(frozen=True)
class CredentialField:
    """Declares one input field the operator must fill in the Tools UI to enable an
    integration provider (e.g. Google needs `client_id` + `client_secret`)."""

    name: str
    label: str
    secret: bool = False
    placeholder: str = ""


@dataclass(frozen=True)
class ActionMeta:
    """Hand-written, human-facing metadata for one action (tool function) exposed by an
    integration. Keyed by function name in `Integration.action_meta`. Falls back to a
    humanized function name when an action has no entry."""

    label: str
    output_description: str = ""
    output_schema: dict[str, Any] | None = None


def _humanize(name: str) -> str:
    """Fallback label for an action with no `ActionMeta` entry, e.g. `gmail_search` →
    `Gmail search`."""
    return name.replace("_", " ").capitalize()


def describe_action(
    schema: dict[str, Any], integration: str, action_meta: dict[str, "ActionMeta"]
) -> dict[str, Any]:
    """Turn one OpenAI function-calling schema into a catalog-ready action descriptor.
    Shared by `Integration.describe_actions` and the builtin tools' equivalent so the
    two produce dicts with the exact same shape."""

    fn = schema["function"]
    name = fn["name"]
    meta = action_meta.get(name)
    return {
        "name": name,
        "integration": integration,
        "label": meta.label if meta else _humanize(name),
        "description": fn.get("description", ""),
        "input_schema": fn["parameters"],
        "output_description": meta.output_description if meta else "",
        "output_schema": meta.output_schema if meta else None,
    }


class Integration(ABC):
    """Top-level contract for a first-party integration.

    Each integration owns its credential storage and its tool functions. The registry
    exposes only `is_configured()` integrations to the agent's toolset.
    """

    # Class attributes — every subclass must set them.
    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    setup_url: ClassVar[str]
    schemas: ClassVar[list[dict[str, Any]]]

    # App-level credentials, optional. When set, the Tools UI shows inputs for these
    # fields and the namespace is used to look them up in `Settings.tool_credentials`.
    # Several integrations sharing the same OAuth client (e.g. all Google ones) share
    # the same namespace.
    credentials_namespace: ClassVar[str | None] = None
    credentials_fields: ClassVar[list[CredentialField]] = []

    # Catalog metadata for the `/tools` endpoint and the frontend's connect UI.
    logo_url: ClassVar[str] = ""
    connect_mode: ClassVar[Literal["oauth", "config"]] = "oauth"
    setup: ClassVar[dict[str, Any]] = {}
    action_meta: ClassVar[dict[str, ActionMeta]] = {}

    def describe_actions(self) -> list[dict[str, Any]]:
        """One catalog-ready descriptor per schema in `self.schemas`."""
        return [describe_action(s, self.name, self.action_meta) for s in self.schemas]

    @abstractmethod
    async def is_configured(self, session: AsyncSession) -> bool: ...

    @abstractmethod
    async def execute(
        self, function_name: str, args: dict[str, Any], session: AsyncSession
    ) -> ToolResult: ...

    # OAuth hooks — default to None for integrations that don't need OAuth.
    # OAuth-based subclasses (e.g. GoogleOAuthIntegration) override these.

    async def oauth_start_url(
        self, session: AsyncSession, state: str, redirect_uri: str
    ) -> str | None:
        """Return the provider's authorize URL to redirect the browser to, or None."""
        return None

    async def oauth_exchange_and_save(
        self, code: str, redirect_uri: str, session: AsyncSession
    ) -> None:
        """Exchange the OAuth code for tokens and persist them. No-op by default."""
        raise NotImplementedError(f"{self.name} does not support OAuth.")
