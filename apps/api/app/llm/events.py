"""Provider-agnostic streaming event types.

The same `AgentEvent` union is yielded by every LLM provider and consumed by the agent
runner / SSE endpoint. The client receives these as JSON payloads in the SSE `data` field,
matching the protocol the legacy Node implementation used.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class TextEvent(TypedDict):
    type: Literal["text"]
    delta: str


class ToolCallEvent(TypedDict):
    type: Literal["tool_call"]
    id: str
    tool: str
    args: str  # raw JSON string (parsed by the executor)


class ToolResultEvent(TypedDict):
    type: Literal["tool_result"]
    id: str
    tool: str
    ok: bool
    result: str


class FinalEvent(TypedDict):
    type: Literal["final"]
    text: str


class ErrorEvent(TypedDict):
    type: Literal["error"]
    message: str


class UsageEvent(TypedDict):
    type: Literal["usage"]
    inputTokens: int
    outputTokens: int


class DoneEvent(TypedDict):
    type: Literal["done"]
    status: str  # 'succeeded' | 'failed' | 'cancelled'


AgentEvent = (
    TextEvent
    | ToolCallEvent
    | ToolResultEvent
    | FinalEvent
    | ErrorEvent
    | UsageEvent
    | DoneEvent
)
