"""Pick a provider implementation by name + API key."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import BadRequest, NotFound
from app.llm.anthropic_client import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.openai_client import OpenAICompatProvider
from app.services.settings import get_settings_for_client

PROVIDER_BASE_URLS = {
    "openai": None,  # OpenAI SDK default
    "anthropic": None,  # Anthropic SDK default
}


async def get_provider_for(session: AsyncSession, provider: str) -> LLMProvider:
    """Resolve the user's stored API key + instantiate the right provider impl."""
    if provider not in PROVIDER_BASE_URLS:
        raise BadRequest(f"Unknown provider: {provider}")

    settings = await get_settings_for_client(session)
    api_key = next((p.api_key for p in settings.providers if p.provider == provider), "")
    if not api_key:
        raise NotFound(f"No API key configured for {provider}.")

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key)
    return OpenAICompatProvider(api_key=api_key, base_url=PROVIDER_BASE_URLS[provider])
