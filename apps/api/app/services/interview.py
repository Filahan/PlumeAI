"""Interview engine for automations + parallel task-title generation."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProviderError
from app.integrations.registry import INTEGRATIONS, list_configured_integrations
from app.llm.base import ChatMessage
from app.llm.factory import get_provider_for

BASE_PROMPT = """You are an automation designer. Interview the user about their intended automation so you can produce a precise, complete prompt for an autonomous agent that will then execute it.

The agent has three built-in tools:
- web_search(query): search the web
- web_fetch(url): GET and parse a web page
- http(method, url, headers?, body?): arbitrary HTTP method to APIs

{INTEGRATIONS}

Gather: (1) the data source / trigger, (2) what to do with the data, (3) the output destination, (4) any auth/credentials the agent will need, (5) schedule preference.

Rules:
- Ask ONE question at a time.
- Prefer 2-4 multiple-choice options when possible. Use open-ended only when needed.
- Respond ONLY as valid JSON. No prose, no code fences. Use one of:
  {{"type":"ask","question":"<one sentence>","options":["A","B","C"]}}
  (omit "options" for open-ended)
  OR
  {{"type":"finalize","skill":"<complete prompt for the agent>"}}
- The "skill" must be a clear instruction in plain English with concrete URLs/parameters the user provided. Include any @<tool> mentions verbatim so the executor knows which integrations to use.
- If the user @-mentions a tool that is NOT in the "Available @-mention integrations" list above, ask them to connect it in Settings first and do not finalize until they do.
- Stop early — 3 to 6 questions max. Don't over-interrogate.
"""

TITLE_SYSTEM = (
    "You generate a concise 3-5 word title for an automation task. "
    "Reply with ONLY the title text — no quotes, no punctuation, no prefix, "
    "in the user's language."
)


@dataclass
class InterviewAsk:
    kind: Literal["ask"]
    question: str
    options: list[str] | None


@dataclass
class InterviewFinalize:
    kind: Literal["finalize"]
    skill: str


InterviewResult = InterviewAsk | InterviewFinalize


async def _build_system_prompt(session: AsyncSession) -> str:
    configured = await list_configured_integrations(session)
    configured_names = {i.name for i in configured}
    if not configured:
        known = [
            f"- @{i.name} (NOT CONNECTED — tell the user to connect it in Settings first)"
            for i in INTEGRATIONS
        ]
        block = "Available @-mention integrations: none connected yet.\n" + (
            "Known but unconnected:\n" + "\n".join(known) if known else ""
        )
    else:
        connected_lines = [f"- @{i.name}: {i.description}" for i in configured]
        unconnected = [
            f"- @{i.name} (NOT CONNECTED)" for i in INTEGRATIONS if i.name not in configured_names
        ]
        block = "Available @-mention integrations the user can reference:\n" + "\n".join(
            connected_lines
        )
        if unconnected:
            block += "\nKnown but not yet connected:\n" + "\n".join(unconnected)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_slash = today.replace("-", "/")
    date_line = (
        f"Today's date is {today}. When the user says 'today', 'yesterday', 'last week', "
        f"etc., write the CONCRETE date(s) into the finalized skill — never the literal "
        f"words 'today' or 'yesterday'. For Gmail searches, use the YYYY/MM/DD format "
        f"(e.g. `after:{today_slash}`)."
    )
    return BASE_PROMPT.replace("{INTEGRATIONS}", block) + "\n\n" + date_line


def _coerce_history(history: list[dict[str, Any]]) -> list[ChatMessage]:
    """Reconstruct chat messages from the stored InterviewMessage history.

    Assistant turns are re-encoded as the JSON shape they originally emitted (so the
    model sees the same wire format on every round)."""
    out: list[ChatMessage] = []
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if role == "assistant":
            blob = {"type": "ask", "question": content, "options": m.get("options") or []}
            out.append(ChatMessage(role="assistant", content=json.dumps(blob)))
        elif role == "user":
            out.append(ChatMessage(role="user", content=content))
    return out


async def _call_json_mode(
    session: AsyncSession, provider_name: str, model: str, messages: list[ChatMessage]
) -> str:
    """Send a request expecting JSON output. Uses OpenAI's response_format directly so we
    bypass the streaming layer for the interviewer (one short JSON response)."""
    if provider_name == "anthropic":
        raise ProviderError("Interview requires an OpenAI or OpenRouter model.")
    # Reuse the existing provider factory to resolve the API key.
    from openai import AsyncOpenAI

    from app.llm.factory import PROVIDER_BASE_URLS
    from app.services.settings import get_settings_for_client

    settings = await get_settings_for_client(session)
    api_key = next((p.api_key for p in settings.providers if p.provider == provider_name), "")
    if not api_key:
        raise ProviderError(f"No API key configured for {provider_name}.")

    client = AsyncOpenAI(api_key=api_key, base_url=PROVIDER_BASE_URLS[provider_name])
    res = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": m.role,
                "content": m.content if m.content is not None else "",
            }
            for m in messages
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return res.choices[0].message.content or ""


async def interview(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    history: list[dict[str, Any]],
    user_message: str,
) -> InterviewResult:
    system_prompt = await _build_system_prompt(session)
    messages = [
        ChatMessage(role="system", content=system_prompt),
        *_coerce_history(history),
        ChatMessage(role="user", content=user_message),
    ]

    raw = await _call_json_mode(session, provider, model, messages)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return InterviewAsk(kind="ask", question=raw.strip()[:500], options=None)

    if parsed.get("type") == "ask" and isinstance(parsed.get("question"), str):
        opts_raw = parsed.get("options")
        opts: list[str] | None = None
        if isinstance(opts_raw, list):
            cleaned = [o for o in opts_raw if isinstance(o, str)]
            opts = cleaned if cleaned else None
        return InterviewAsk(kind="ask", question=parsed["question"], options=opts)

    if (
        parsed.get("type") == "finalize"
        and isinstance(parsed.get("skill"), str)
        and parsed["skill"].strip()
    ):
        return InterviewFinalize(kind="finalize", skill=parsed["skill"].strip())

    raise ProviderError("Interviewer response did not match the expected shape.")


async def generate_task_title(
    session: AsyncSession, provider: str, model: str, user_intent: str
) -> str:
    """Best-effort 3-5 word title from the user's first message. Returns '' on failure."""
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
            max_tokens=40,
            messages=[
                {"role": "system", "content": TITLE_SYSTEM},
                {"role": "user", "content": user_intent},
            ],
        )
        raw = res.choices[0].message.content or ""
        return raw.strip().strip("\"'`.!?,").strip()[:80]
    except Exception:  # noqa: BLE001
        return ""
