"""Settings load/save logic — encrypts provider keys, decrypts on read, never exposes
tool tokens to the client."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.db.models import Settings as SettingsRow
from app.schemas.settings import (
    DEFAULT_SETTINGS,
    DefaultModel,
    ProviderConfig,
    SettingsPayload,
    ToolConnection,
)


async def _get_or_create_row(session: AsyncSession) -> SettingsRow:
    """Load the single settings row (id=1), creating it with defaults if missing."""
    row = (
        await session.execute(select(SettingsRow).where(SettingsRow.id == 1))
    ).scalar_one_or_none()
    if row is None:
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


async def get_settings_for_client(session: AsyncSession) -> SettingsPayload:
    """Decrypt provider keys, expose only `{connected}` for tools — no secrets leak."""
    row = await _get_or_create_row(session)

    providers: list[ProviderConfig] = []
    for p in row.providers or []:
        api_key = ""
        ct = p.get("apiKeyCiphertext")
        iv = p.get("apiKeyIv")
        if ct and iv:
            try:
                api_key = decrypt(iv, ct)
            except Exception:
                # Corrupt or wrong-key ciphertext: silently drop the plaintext, keep the
                # row so the client can fix it manually rather than losing the metadata.
                api_key = ""
        providers.append(
            ProviderConfig(
                id=p["id"],
                provider=p["provider"],
                label=p["label"],
                api_key=api_key,
            )
        )

    tools: dict[str, ToolConnection] = {}
    for name, blob in (row.tools or {}).items():
        tools[name] = ToolConnection(
            connected=bool(blob.get("ciphertext") and blob.get("iv"))
        )

    tool_credentials = {
        name: bool(blob and blob.get("ciphertext") and blob.get("iv"))
        for name, blob in (row.tool_credentials or {}).items()
    }

    return SettingsPayload(
        providers=providers,
        default_model=DefaultModel.model_validate(row.default_model),
        tools=tools,
        tool_credentials=tool_credentials,
        timezone=row.timezone or "UTC",
    )


async def get_timezone(session: AsyncSession) -> str:
    """The workspace IANA timezone, used to resolve schedules and `{{trigger.date}}`.

    Read straight off the row rather than through `get_settings_for_client`, which shapes
    a client payload (and decrypts keys) the scheduler and executor have no use for.
    """
    row = await _get_or_create_row(session)
    return row.timezone or "UTC"


async def save_settings(session: AsyncSession, payload: SettingsPayload) -> None:
    """Encrypt each provider's apiKey, persist; leave the tools blob untouched."""
    row = await _get_or_create_row(session)

    encrypted_providers: list[dict[str, Any]] = []
    for p in payload.providers:
        entry: dict[str, Any] = {
            "id": p.id,
            "provider": p.provider,
            "label": p.label,
        }
        if p.api_key:
            enc = encrypt(p.api_key)
            entry["apiKeyCiphertext"] = enc["ct"]
            entry["apiKeyIv"] = enc["iv"]
        else:
            entry["apiKeyCiphertext"] = ""
            entry["apiKeyIv"] = ""
        encrypted_providers.append(entry)

    row.providers = encrypted_providers
    row.default_model = payload.default_model.model_dump(by_alias=True)
    # Already validated as a real IANA zone by `SettingsPayload`, so the scheduler can
    # build a trigger with it without a second check.
    row.timezone = payload.timezone
    # tools is managed by the OAuth flows + disconnect_tool; ignore client-supplied value.


async def disconnect_tool(session: AsyncSession, name: str) -> None:
    """Drop the encrypted token blob for `tools[name]`, marking the tool not connected."""
    row = await _get_or_create_row(session)
    tools = dict(row.tools or {})
    if name in tools:
        del tools[name]
    row.tools = tools
