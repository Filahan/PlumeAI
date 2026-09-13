"""Catalog of tool actions available to the agent: integrations + builtin, merged with
each integration's connection status.

Backs `GET /tools` so the frontend stops hardcoding the integration catalog (see
`apps/web/src/lib/tools/registry-client.ts`, which this catalog is meant to replace).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import Integration
from app.integrations.registry import INTEGRATIONS
from app.tools.builtin import describe_builtin_actions


@dataclass
class CatalogAction:
    """Protocol-compatible action descriptor.

    Mirrors the shape of the `ActionMeta` dataclass another (parallel) task defines in
    `app.services.documents` — `(name, integration, label, description, input_schema)`
    — so a `Catalog` satisfies that module's `find_action`/`is_connected` protocol by
    duck typing, without either module importing the other.
    """

    name: str
    integration: str
    label: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class CatalogIntegration:
    name: str
    label: str
    description: str
    logo_url: str
    connect_mode: str
    setup_url: str
    credentials_namespace: str | None
    credentials_fields: list[dict[str, Any]]
    setup: dict[str, Any]
    connected: bool
    actions: list[dict[str, Any]]


@dataclass
class Catalog:
    integrations: list[CatalogIntegration]
    builtin_actions: list[dict[str, Any]]

    def _all_actions(self) -> list[dict[str, Any]]:
        actions = list(self.builtin_actions)
        for integ in self.integrations:
            actions.extend(integ.actions)
        return actions

    def find_action(self, name: str) -> CatalogAction | None:
        for action in self._all_actions():
            if action["name"] == name:
                return CatalogAction(
                    name=action["name"],
                    integration=action["integration"],
                    label=action["label"],
                    description=action["description"],
                    input_schema=action["input_schema"],
                )
        return None

    def is_connected(self, integration: str) -> bool:
        if integration == "builtin":
            return True
        return any(i.name == integration and i.connected for i in self.integrations)


async def _build_integration(integ: Integration, session: AsyncSession) -> CatalogIntegration:
    return CatalogIntegration(
        name=integ.name,
        label=integ.label,
        description=integ.description,
        logo_url=integ.logo_url,
        connect_mode=integ.connect_mode,
        setup_url=integ.setup_url,
        credentials_namespace=integ.credentials_namespace,
        credentials_fields=[
            {"name": f.name, "label": f.label, "secret": f.secret, "placeholder": f.placeholder}
            for f in integ.credentials_fields
        ],
        setup=dict(integ.setup),
        connected=await integ.is_configured(session),
        actions=integ.describe_actions(),
    )


async def build_catalog(session: AsyncSession) -> Catalog:
    """Assemble the full catalog: every registered integration (with live connection
    status) plus the always-on builtin tools."""
    integrations = [await _build_integration(integ, session) for integ in INTEGRATIONS]
    return Catalog(integrations=integrations, builtin_actions=describe_builtin_actions())
