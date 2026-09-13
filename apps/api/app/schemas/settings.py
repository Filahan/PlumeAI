"""Settings API schemas — what the client sends and receives.

Secrets policy:
- On GET /settings, `provider.apiKey` is the **plaintext** (decrypted server-side from DB).
- On PUT /settings, `provider.apiKey` is the **plaintext** (encrypted server-side before DB write).
- Tools tokens are NEVER exposed; only `tools[name].connected` (and optional metadata).
"""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

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
    # Per-provider credential status (e.g. {"google": True, "discord": False}).
    # Only booleans — secrets never reach the client.
    tool_credentials: dict[str, bool] = Field(default_factory=dict)
    # IANA timezone the workspace lives in. Schedule triggers that don't carry one of
    # their own fire in it, and it is what `{{trigger.date}}` means inside a run — so
    # "every weekday at 8" is 8am where the user is, not 8am UTC.
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value


DEFAULT_SETTINGS = SettingsPayload(
    providers=[],
    default_model=DefaultModel(provider="openai", model="gpt-4o"),
    tools={},
    tool_credentials={},
    timezone="UTC",
)
