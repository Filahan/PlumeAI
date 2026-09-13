"""Provider-agnostic structured output.

Getting a machine-readable object out of an LLM is done the same way for every provider we
support: declare a single function tool whose parameters *are* the JSON Schema we want,
force the model to call it, and read the arguments back. That works identically on OpenAI
and Anthropic because `LLMProvider.stream_chat` already normalizes tool calls.

Anything the model gets wrong (malformed JSON, a payload that violates the schema) is fed
back to it as a follow-up turn so it can try again. Anything the *provider* gets wrong
(auth, rate limits, a truncated response) propagates immediately — retrying won't help.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

import structlog
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProviderError, ValidationFailure
from app.llm.base import ChatMessage, LLMProvider
from app.llm.events import AgentEvent
from app.llm.factory import get_provider_for

log = structlog.get_logger("app.llm.structured")

RETRY_TEMPLATE = (
    "Your previous output was invalid: {error} Call the tool again with a valid payload."
)

NO_TOOL_CALL = "(no tool call)"


@dataclass(frozen=True)
class StructuredResult:
    """The validated payload plus what the round trip (including retries) cost."""

    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class _Invalid:
    """Why a payload was rejected.

    `message` is written for the model and may quote the offending payload, so it goes in
    the retry prompt only. The remaining fields are safe to log.
    """

    message: str
    kind: str
    json_path: str | None = None
    validator: str | None = None


@dataclass
class _Attempt:
    """What one streaming round produced."""

    raw: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


async def _drain(stream: AsyncIterator[AgentEvent]) -> _Attempt:
    """Consume a provider stream, keeping the first tool call's arguments and the usage.

    `aclosing` guarantees the underlying async generator is finalized (closing the HTTP
    response) even though we stop reading as soon as we have what we need.
    """
    attempt = _Attempt()
    async with aclosing(stream) as events:
        async for ev in events:
            kind = ev.get("type")
            if kind == "tool_call" and attempt.raw is None:
                attempt.raw = ev.get("args")
            elif kind == "usage":
                attempt.input_tokens = ev["inputTokens"]
                attempt.output_tokens = ev["outputTokens"]
    return attempt


def _check(raw: str, validator: Draft202012Validator) -> dict[str, Any] | _Invalid:
    """Parse + schema-check the tool arguments: the payload, or why it was rejected."""
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        return _Invalid(
            message=f"the arguments were not valid JSON ({exc}).", kind="invalid_json"
        )
    if not isinstance(payload, dict):
        return _Invalid(
            message="the arguments must be a JSON object, not a bare value or list.",
            kind="not_an_object",
        )
    error: ValidationError | None = next(iter(validator.iter_errors(payload)), None)
    if error is not None:
        return _Invalid(
            message=f"the payload did not match the schema ({error.message}).",
            kind="schema_violation",
            json_path=error.json_path,
            validator=str(error.validator),
        )
    return payload


async def complete_json(
    provider: LLMProvider,
    model: str,
    messages: list[ChatMessage],
    schema: dict[str, Any],
    *,
    name: str = "emit",
    description: str = "Return the result.",
    max_retries: int = 1,
) -> StructuredResult:
    """Ask `model` for one object matching `schema`, retrying on invalid output.

    Raises `ValidationFailure` when `schema` itself is not a valid JSON Schema, and
    `ProviderError` when the model still hasn't produced a valid payload after
    `max_retries` extra attempts (`extra={"reason": "invalid_output"}`) or when the
    provider itself failed (`extra={"reason": "upstream"}`).
    """
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValidationFailure(f"Invalid output schema: {exc.message}") from exc
    validator = Draft202012Validator(schema)

    tools = [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        }
    ]
    tool_choice = {"type": "function", "function": {"name": name}}

    convo = list(messages)
    total_in = 0
    total_out = 0
    invalid = _Invalid(message="the model returned no tool call.", kind="no_tool_call")

    for attempt_no in range(max_retries + 1):
        try:
            attempt = await _drain(
                provider.stream_chat(
                    model=model, messages=convo, tools=tools, tool_choice=tool_choice
                )
            )
        except ProviderError as exc:
            # An upstream failure is not something a reworded prompt can fix.
            exc.extra.setdefault("reason", "upstream")
            raise

        total_in += attempt.input_tokens
        total_out += attempt.output_tokens

        if attempt.raw is None:
            invalid = _Invalid(message="the model returned no tool call.", kind="no_tool_call")
        else:
            checked = _check(attempt.raw, validator)
            if not isinstance(checked, _Invalid):
                return StructuredResult(
                    data=checked, input_tokens=total_in, output_tokens=total_out
                )
            invalid = checked

        # Only the schema-shaped facts are logged — `invalid.message` can quote the
        # model's payload, which may carry user data, so it stays in the prompt.
        log.warning(
            "structured_output_invalid",
            model=model,
            tool=name,
            attempt=attempt_no,
            kind=invalid.kind,
            json_path=invalid.json_path,
            validator=invalid.validator,
        )

        if attempt_no >= max_retries:
            break

        convo = [
            *convo,
            ChatMessage(
                role="assistant", content=attempt.raw if attempt.raw is not None else NO_TOOL_CALL
            ),
            ChatMessage(role="user", content=RETRY_TEMPLATE.format(error=invalid.message)),
        ]

    raise ProviderError(
        f"{model} did not return a valid `{name}` payload after "
        f"{max_retries + 1} attempt(s): {invalid.message}",
        extra={"reason": "invalid_output"},
    )


async def complete_json_for(
    session: AsyncSession,
    provider_name: str,
    model: str,
    messages: list[ChatMessage],
    schema: dict[str, Any],
    *,
    name: str = "emit",
    description: str = "Return the result.",
    max_retries: int = 1,
) -> StructuredResult:
    """`complete_json` against the provider the user has configured under `provider_name`."""
    provider = await get_provider_for(session, provider_name)
    return await complete_json(
        provider,
        model,
        messages,
        schema,
        name=name,
        description=description,
        max_retries=max_retries,
    )
