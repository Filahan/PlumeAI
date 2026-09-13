"""Filling an action step's `kind: "ai"` input fields in one structured call.

An action step's input map can mix three kinds of `FieldValue`: `literal` and `ref` are
resolved deterministically by `app.services.refs`, but `ai` fields carry a natural-language
instruction ("Unread emails from dana@acme.com since yesterday") that only a model can turn
into the value the action's JSON Schema actually wants.

All of a step's `ai` fields are filled by **one** `complete_json` call rather than one call
per field: the fields of a single action are usually correlated (a query and the window it
applies to), the model sees the whole action at once, and it costs one round trip instead of
N. The schema handed to the model is assembled from the action's own input schema, so the
answer is type-checked against the same contract the tool will be called with.

Everything here is pure except the provider call, so it unit-tests against a fake provider.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.llm.base import ChatMessage, LLMProvider
from app.llm.structured import StructuredResult, complete_json

__all__ = [
    "MAX_CONTEXT_CHARS",
    "MAX_STEP_OUTPUT_CHARS",
    "build_fill_schema",
    "fill_ai_fields",
    "render_prior_outputs",
]

# How much of a single prior step's output may appear in a prompt. A step that fetched 200
# emails would otherwise blow the context window on its own.
MAX_STEP_OUTPUT_CHARS = 6_000
# Total budget for the prior-outputs block, across all steps.
MAX_CONTEXT_CHARS = 24_000
# A truncated entry never shrinks below this, so every step stays recognizable.
MIN_STEP_OUTPUT_CHARS = 200

_TRUNCATION_SUFFIX = "…[truncated]"

FILL_TOOL_NAME = "fill_fields"

SYSTEM_PROMPT = """\
You fill in the input fields of one step of an automation.

For each field you are given the field's name and a plain-language instruction describing \
what should go in it. Produce a value for every field by following its instruction, using \
ONLY the automation context given to you (the earlier steps' outputs and today's date). \
Never invent facts that are not in that context.

Rules:
- Respect each field's declared type, format and enum — the payload is schema-checked.
- Write dates in ISO 8601 (YYYY-MM-DD, or a full timestamp when a time matters), unless the \
field's own description asks for a different format.
- Resolve relative wording ("yesterday", "this week") against today's date.
- Keep values minimal and literal: a search query is a query, not a sentence about one.
- If the context genuinely does not determine a value, choose the most reasonable default \
consistent with the instruction rather than leaving the field out."""


class ActionLike(Protocol):
    """The slice of `app.services.catalog.CatalogAction` this module reads."""

    name: str
    label: str
    description: str
    input_schema: dict[str, Any]


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _clip(text: str, limit: int) -> str:
    """Cap `text` at `limit` characters, marking it as cut. Idempotent.

    Already-clipped text keeps a single marker instead of collecting one per pass — the
    budget loop below can clip the same entry twice.
    """
    if len(text) <= limit:
        return text
    body = text[: -len(_TRUNCATION_SUFFIX)] if text.endswith(_TRUNCATION_SUFFIX) else text
    keep = max(0, limit - len(_TRUNCATION_SUFFIX))
    return body[:keep] + _TRUNCATION_SUFFIX


def render_prior_outputs(
    outputs: dict[str, Any],
    *,
    per_step_cap: int = MAX_STEP_OUTPUT_CHARS,
    total_cap: int = MAX_CONTEXT_CHARS,
) -> str:
    """Render earlier steps' outputs as one compact JSON object, within a char budget.

    Each step's output is capped at `per_step_cap` on its own; if the whole block is still
    over `total_cap`, entries are shrunk **oldest first** (dict order is execution order),
    because the step a prompt is about is almost always the most recent one. A shrunk entry
    becomes a JSON *string* ending in `…[truncated]` instead of the original value, so the
    result stays valid JSON and the model can see that it is looking at a fragment.

    Both caps are **approximate**, and deliberately so. They count characters of rendered
    JSON, not tokens, and `MIN_STEP_OUTPUT_CHARS` is a floor no entry drops below — so a
    run with many steps can exceed `total_cap` rather than render steps the prompt can't
    identify. The point is to stop one enormous output from swallowing the context window,
    not to hit a byte target.
    """
    # `raw` is the value's compact JSON; once an entry has been clipped it is rendered as
    # a JSON *string* holding that clipped text instead, so the block stays parseable and
    # the model can see it is looking at a fragment.
    entries: list[list[Any]] = []
    for step_id, value in outputs.items():
        raw = _compact(value)
        clipped = len(raw) > per_step_cap
        entries.append([step_id, _clip(raw, per_step_cap) if clipped else raw, clipped])

    def _width(entry: list[Any]) -> int:
        _, text, clipped = entry
        return len(_compact(text)) if clipped else len(text)

    total = sum(_width(e) for e in entries)
    for entry in entries:
        if total <= total_cap:
            break
        width = _width(entry)
        room = total_cap - (total - width)
        # A clipped entry is re-rendered as a JSON *string*, whose quotes and escapes also
        # count against the budget. Charging the un-clipped text's overhead against `room`
        # is an over-estimate (a shorter prefix can only need fewer escapes), which is the
        # safe direction: the clipped entry always lands inside its share.
        text: str = entry[1]
        overhead = len(_compact(text)) - len(text)
        keep = max(MIN_STEP_OUTPUT_CHARS, min(len(text), room - overhead))
        entry[1] = _clip(entry[1], keep)
        entry[2] = True
        total += _width(entry) - width

    return (
        "{"
        + ",".join(
            f"{_compact(step_id)}:{_compact(text) if clipped else text}"
            for step_id, text, clipped in entries
        )
        + "}"
    )


def build_fill_schema(
    fields: dict[str, str], field_schemas: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """One object schema with a property per AI field, every one of them required.

    A field with no schema of its own (the action isn't in the catalog, or its input schema
    doesn't describe that key) gets a permissive `{}` rather than being dropped — the model
    still has to produce *something* for it, which is better than calling the tool without
    the field at all.
    """
    properties: dict[str, Any] = {}
    for name, instruction in fields.items():
        schema = dict(field_schemas.get(name) or {})
        # The instruction is the most useful description the model can get for this field;
        # keep any catalog description alongside it rather than replacing it.
        existing = schema.get("description")
        schema["description"] = f"{existing} {instruction}".strip() if existing else instruction
        properties[name] = schema
    return {
        "type": "object",
        "properties": properties,
        "required": list(fields),
        "additionalProperties": False,
    }


def _user_message(
    *,
    automation_name: str,
    automation_description: str,
    step_name: str,
    action: ActionLike | None,
    fields: dict[str, str],
    prior_outputs: dict[str, Any],
    ctx: dict[str, Any],
) -> str:
    action_name = getattr(action, "name", None) or "(unknown action)"
    action_label = getattr(action, "label", "") or action_name
    action_description = getattr(action, "description", "") or "(no description available)"

    parts = [
        f"Automation: {automation_name}",
    ]
    if automation_description:
        parts.append(f"What it does: {automation_description}")
    parts.extend(
        [
            f"Today is {ctx.get('date')} ({ctx.get('timezone')}); the current time is "
            f"{ctx.get('now')}.",
            "",
            f'Step: "{step_name}" — runs the action `{action_name}` ({action_label}).',
            f"Action description: {action_description}",
            "",
            "Fields to fill:",
            *(f"- {name}: {instruction}" for name, instruction in fields.items()),
            "",
            "Outputs of the steps that already ran, keyed by step id:",
            render_prior_outputs(prior_outputs) if prior_outputs else "{}",
            "",
            f"Call `{FILL_TOOL_NAME}` once with a value for every field listed above.",
        ]
    )
    return "\n".join(parts)


async def fill_ai_fields(
    *,
    provider: LLMProvider,
    model: str,
    automation_name: str,
    automation_description: str,
    step_name: str,
    action: ActionLike | None,
    fields: dict[str, str],
    field_schemas: dict[str, dict[str, Any]],
    prior_outputs: dict[str, Any],
    ctx: dict[str, Any],
) -> StructuredResult:
    """Fill every `ai` field of one action step in a single structured call.

    `fields` maps field name → the author's instruction for it; `field_schemas` maps field
    name → that field's slice of the action's input schema. The returned
    `StructuredResult.data` has exactly the keys of `fields`, and carries the tokens the
    call cost so the run can bill them.

    Raises whatever `complete_json` raises: `ValidationFailure` for an unusable schema,
    `ProviderError` for an upstream failure or output the model could not get right.
    """
    schema = build_fill_schema(fields, field_schemas)
    messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=_user_message(
                automation_name=automation_name,
                automation_description=automation_description,
                step_name=step_name,
                action=action,
                fields=fields,
                prior_outputs=prior_outputs,
                ctx=ctx,
            ),
        ),
    ]
    return await complete_json(
        provider,
        model,
        messages,
        schema,
        name=FILL_TOOL_NAME,
        description="Provide a value for every input field of this step.",
    )
