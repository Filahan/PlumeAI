"""Catalog of tool actions available to the agent: integrations + builtin, merged with
each integration's connection status.

Backs `GET /tools` so the frontend stops hardcoding the integration catalog (see
`apps/web/src/lib/tools/registry-client.ts`, which this catalog is meant to replace).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import Integration
from app.integrations.registry import INTEGRATIONS
from app.tools.base import BUILTIN_INTEGRATION, CatalogAction
from app.tools.builtin import describe_builtin_actions


@dataclass
class CatalogIntegration:
    name: str
    label: str
    description: str
    logo_url: str
    connect_mode: Literal["oauth", "config"]
    setup_url: str
    credentials_namespace: str | None
    credentials_fields: list[dict[str, Any]]
    setup: dict[str, Any]
    connected: bool
    actions: list[CatalogAction]


@dataclass
class Catalog:
    integrations: list[CatalogIntegration]
    builtin_actions: list[CatalogAction]
    _index: dict[str, CatalogAction] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Builtins first, then integration actions — a name collision (unlikely, but
        # cheap to guard against) resolves in favor of the integration action.
        index: dict[str, CatalogAction] = {a.name: a for a in self.builtin_actions}
        for integ in self.integrations:
            for action in integ.actions:
                index[action.name] = action
        self._index = index

    def find_action(self, name: str) -> CatalogAction | None:
        return self._index.get(name)

    def is_connected(self, integration: str) -> bool:
        if integration == BUILTIN_INTEGRATION:
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
        setup=copy.deepcopy(integ.setup),
        connected=await integ.is_configured(session),
        actions=integ.describe_actions(),
    )


async def build_catalog(session: AsyncSession) -> Catalog:
    """Assemble the full catalog: every registered integration (with live connection
    status) plus the always-on builtin tools."""
    integrations = [await _build_integration(integ, session) for integ in INTEGRATIONS]
    return Catalog(integrations=integrations, builtin_actions=describe_builtin_actions())
