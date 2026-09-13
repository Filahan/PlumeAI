"""Best-effort conversation titles.

A title is a nicety, never a requirement: every failure path here — an unsupported
provider, a missing API key, a refusal, a network error — returns `""` and the caller
keeps whatever title it already had. Nothing in this module is allowed to raise.

Anthropic is skipped outright rather than given a translated request: titling is a
one-shot, 40-token call that isn't worth a second provider path, and the caller already
handles the empty-string answer.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

CHAT_TITLE_SYSTEM = (
    "You generate a very short 2-5 word title that summarizes the topic of a chat "
    "conversation, based on the user's first message. Reply with ONLY the title text — "
    "no quotes, no punctuation, no prefix, no explanation. Match the language of the "
    "user's message; if it is short or ambiguous, default to English. Do not invent a "
    "topic that is not in the message."
)

MAX_TITLE_CHARS = 80
MAX_TITLE_TOKENS = 40


async def _generate_title(
    session: AsyncSession,
    provider: str,
    model: str,
    system_prompt: str,
    user_intent: str,
) -> str:
    """Ask the model for a short title. Returns '' on any failure."""
    if provider == "anthropic":
        return ""
    try:
        from openai import AsyncOpenAI

        from app.llm.factory import PROVIDER_BASE_URLS
        from app.services.settings import get_settings_for_client

        settings = await get_settings_for_client(session)
        api_key = next((p.api_key for p in settings.providers if p.provider == provider), "")
        if not api_key:
            return ""
        client = AsyncOpenAI(api_key=api_key, base_url=PROVIDER_BASE_URLS[provider])
        res = await client.chat.completions.create(
            model=model,
            max_tokens=MAX_TITLE_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_intent},
            ],
        )
        raw = res.choices[0].message.content or ""
        return raw.strip().strip("\"'`.!?,").strip()[:MAX_TITLE_CHARS]
    except Exception:  # noqa: BLE001 — a title is never worth failing the request for
        return ""


async def generate_chat_title(
    session: AsyncSession, provider: str, model: str, user_message: str
) -> str:
    """Best-effort 2-5 word title for a chat conversation. Returns '' on failure."""
    return await _generate_title(session, provider, model, CHAT_TITLE_SYSTEM, user_message)
