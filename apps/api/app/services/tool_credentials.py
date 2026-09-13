"""App-level credentials for tool integrations (Google OAuth client, Discord bot, …).

These are credentials the *operator* sets once (via the Tools UI) and that every user
session shares. Distinct from `settings.tools[name]` which stores per-user OAuth tokens
obtained at runtime.

Stored as JSON-encoded blobs encrypted with `app.crypto.encrypt`, keyed in
`Settings.tool_credentials` by integration namespace (e.g. "google", "discord").
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.models import Settings as SettingsRow
from app.schemas.settings import DEFAULT_SETTINGS

log = structlog.get_logger("app.services.tool_credentials")


async def _get_or_create_row(session: AsyncSession) -> SettingsRow:
    row = (
        await session.execute(select(SettingsRow).where(SettingsRow.id == 1))
    ).scalar_one_or_none()
    if row is None:
        # Seed the same defaults `app.services.settings` would: this path can be the
        # first thing to touch the settings row on a fresh database (the tools catalog
        # is built before anyone opens the settings page), and an empty `default_model`
        # would then fail to validate on the next read.
        row = SettingsRow(
            id=1,
            providers=[],
            default_model=DEFAULT_SETTINGS.default_model.model_dump(by_alias=True),
            tools={},
            tool_credentials={},
        )
        session.add(row)
        await session.flush()
    return row


async def get_credentials(
    session: AsyncSession, namespace: str
) -> dict[str, str] | None:
    """Decrypt and return the credentials dict for `namespace`, or None if absent."""
    row = await _get_or_create_row(session)
    blob = (row.tool_credentials or {}).get(namespace)
    if not blob or not blob.get("ciphertext") or not blob.get("iv"):
        return None
    try:
        raw = decrypt(blob["iv"], blob["ciphertext"])
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {k: str(v) for k, v in parsed.items()}
        return None
    except Exception:  # noqa: BLE001
        log.warning("tool_credentials_decrypt_failed", namespace=namespace, exc_info=True)
        return None


async def save_credentials(
    session: AsyncSession, namespace: str, fields: dict[str, str]
) -> None:
    """Encrypt and persist the credentials dict for `namespace`."""
    row = await _get_or_create_row(session)
    enc = encrypt(json.dumps(fields, separators=(",", ":")))
    creds: dict[str, Any] = dict(row.tool_credentials or {})
    creds[namespace] = {"ciphertext": enc["ct"], "iv": enc["iv"]}
    row.tool_credentials = creds


async def clear_credentials(session: AsyncSession, namespace: str) -> None:
    row = await _get_or_create_row(session)
    creds = dict(row.tool_credentials or {})
    creds.pop(namespace, None)
    row.tool_credentials = creds


async def credentials_status(session: AsyncSession) -> dict[str, bool]:
    """Map `{namespace: configured}` for the client. Never exposes secrets."""
    row = await _get_or_create_row(session)
    return {
        name: bool(blob and blob.get("ciphertext") and blob.get("iv"))
        for name, blob in (row.tool_credentials or {}).items()
    }
