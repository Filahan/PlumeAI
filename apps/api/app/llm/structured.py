"""Provider-agnostic structured output.

Getting a machine-readable object out of an LLM is done the same way for every provider we
support: declare a single function tool whose parameters *are* the JSON Schema we want,
force the model to call it, and read the arguments back. That works identically on OpenAI,
OpenRouter and Anthropic because `LLMProvider.stream_chat` already normalizes tool calls.

Anything the model gets wrong (malformed JSON, a payload that violates the schema) is fed
back to it as a follow-up turn so it can try again.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProviderError
from app.llm.base import ChatMessage
from app.llm.factory import get_provider_for

log = structlog.get_logger("app.llm.structured")

RETRY_TEMPLATE = (
    "Your previous output was invalid: {error} "
    "Call the tool again with a valid payload."
)


async def _first_tool_call_args(stream: Any) -> tuple[str | None, str | None]:
    """Drain a provider stream, returning (raw args of the first tool call, error message)."""
    raw: str | None = None
    error: str | None = None
    async for ev in stream:
        kind = ev.get("type")
        if kind == "tool_call" and raw is None:
            raw = ev.get("args")
        elif kind == "error":
            error = ev.get("message")
        elif kind == "done":
            break
    return raw, error


def _validate(raw: str, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Parse + schema-check the tool arguments. Returns (payload, error message)."""
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        return None, f"the arguments were not valid JSON ({exc})."
    if not isinstance(payload, dict):
        return None, "the arguments must be a JSON object, not a bare value or list."
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        return None, f"the payload did not match the schema ({exc.message})."
    return payload, None


async def complete_json(
    session: AsyncSession,
    provider_name: str,
    model: str,
    messages: list[ChatMessage],
    schema: dict[str, Any],
    *,
    name: str = "emit",
    description: str = "Return the result.",
    max_retries: int = 1,
) -> dict[str, Any]:
    """Ask `model` for one object matching `schema`, retrying on invalid output.

    Raises `ProviderError` when the model still hasn't produced a valid payload after
    `max_retries` extra attempts.
    """
    provider = await get_provider_for(session, provider_name)
    tools = [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        }
    ]
    tool_choice = {"type": "function", "function": {"name": name}}

    convo = list(messages)
    last_error = "the model returned no tool call."

    for attempt in range(max_retries + 1):
        raw, stream_error = await _first_tool_call_args(
            provider.stream_chat(
                model=model, messages=convo, tools=tools, tool_choice=tool_choice
            )
        )

        if raw is None:
            last_error = stream_error or "the model returned no tool call."
        else:
            payload, last_error = _validate(raw, schema)
            if payload is not None:
                return payload

        log.warning(
            "structured_output_invalid",
            provider=provider_name,
            model=model,
            tool=name,
            attempt=attempt,
            error=last_error,
        )

        if attempt >= max_retries:
            break

        convo = [
            *convo,
            ChatMessage(role="assistant", content=raw or "(no tool call)"),
            ChatMessage(role="user", content=RETRY_TEMPLATE.format(error=last_error)),
        ]

    raise ProviderError(
        f"{provider_name} did not return a valid `{name}` payload after "
        f"{max_retries + 1} attempt(s): {last_error}"
    )
