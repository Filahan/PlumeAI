"""Settings API schemas — what the client sends and receives.

Secrets policy:
- On GET /settings, `provider.apiKey` is the **plaintext** (decrypted server-side from DB).
- On PUT /settings, `provider.apiKey` is the **plaintext** (encrypted server-side before DB write).
- Tools tokens are NEVER exposed; only `tools[name].connected` (and optional metadata).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.base import APISchema

Provider = Literal["openai", "anthropic", "openrouter"]


class ProviderConfig(APISchema):
    id: str
    provider: Provider
    label: str
    api_key: str = ""  # plaintext; encrypted at rest server-side


class DefaultModel(APISchema):
    provider: Provider
    model: str


class ToolConnection(APISchema):
    connected: bool = False
    expires_at: int | None = None  # unix ms; omitted when unknown
    scope: str | None = None


class SettingsPayload(APISchema):
    providers: list[ProviderConfig] = Field(default_factory=list)
    default_model: DefaultModel
    tools: dict[str, ToolConnection] = Field(default_factory=dict)


DEFAULT_SETTINGS = SettingsPayload(
    providers=[],
    default_model=DefaultModel(provider="openai", model="gpt-4o"),
    tools={},
)
