"""Single-user identity.

PlumeAI is self-hosted and single-tenant: there is no login. Every request acts as the
one admin user. Routers keep depending on `CurrentUser` so a real auth layer can be
plugged back in at this single point if the deployment ever needs one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

SESSION_SUBJECT = "admin"


def get_current_user() -> str:
    """FastAPI dependency: the single admin user, always."""
    return SESSION_SUBJECT


CurrentUser = Annotated[str, Depends(get_current_user)]
