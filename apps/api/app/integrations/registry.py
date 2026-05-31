"""Central list of available integrations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import Integration
from app.integrations.gmail import gmail_integration

# Add new integrations here. Each must implement the `Integration` protocol.
INTEGRATIONS: list[Integration] = [gmail_integration]


def find_integration_for_function(function_name: str) -> Integration | None:
    """Map a tool function name (e.g. `gmail_send`) → the owning integration."""
    for integ in INTEGRATIONS:
        for s in integ.schemas:
            if s["function"]["name"] == function_name:
                return integ
    return None


def find_integration_by_name(name: str) -> Integration | None:
    return next((i for i in INTEGRATIONS if i.name == name), None)


async def list_configured_integrations(session: AsyncSession) -> list[Integration]:
    out: list[Integration] = []
    for integ in INTEGRATIONS:
        if await integ.is_configured(session):
            out.append(integ)
    return out
