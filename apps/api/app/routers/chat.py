"""Chat streaming router — POST /chat/stream wraps the LLM provider in SSE.

This phase ships *chat-only* (no tool calling). Phase 4 wraps the provider stream in the
agent runner to add tool execution.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import stream_agent
from app.auth import CurrentUser
from app.db.base import get_session
from app.errors import AppError
from app.llm.base import ChatMessage
from app.llm.factory import get_provider_for
from app.schemas.chat import ChatStreamRequest
from app.services.usage import record_usage
from app.tools.registry import list_available_tool_schemas

router = APIRouter(prefix="/chat", tags=["chat"])
log = structlog.get_logger("app.chat")

DBSession = Annotated[AsyncSession, Depends(get_session)]

CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Reply concisely; the user sees Markdown so use it when "
    "useful (lists, code fences, links)."
)


def _sse(event: dict) -> dict:
    """Wrap a payload as the sse-starlette expected dict shape."""
    return {"data": json.dumps(event, separators=(",", ":"))}


@router.post("/stream")
async def chat_stream(
    body: ChatStreamRequest,
    request: Request,
    user: CurrentUser,
    session: DBSession,
) -> EventSourceResponse:
    """Stream a single chat-completion round as SSE.

    The client receives the same event protocol as the legacy Node implementation:
    `text` deltas + final `usage` + `done`. Errors are emitted as `error` events.
    """
    provider_name = body.provider
    model = body.model

    # Resolve provider + API key BEFORE the stream starts so configuration errors come
    # back as a proper 4xx Problem Details rather than disappearing into the SSE stream.
    provider = await get_provider_for(session, provider_name)

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=CHAT_SYSTEM_PROMPT),
        *[ChatMessage(role=t.role, content=t.content) for t in body.history],
        ChatMessage(role="user", content=body.new_message),
    ]
    # Anthropic doesn't support our tool-call format yet, so route it through the provider
    # directly without tools. OpenAI + OpenRouter go through the agent runner with all
    # configured tools (built-ins + every connected integration).
    tools = None if provider_name == "anthropic" else await list_available_tool_schemas(session)

    async def generator() -> AsyncIterator[dict]:
        input_tokens = 0
        output_tokens = 0
        status = "succeeded"
        try:
            async for event in stream_agent(
                provider=provider,
                model=model,
                messages=messages,
                tools=tools,
                session=session,
            ):
                if await request.is_disconnected():
                    log.info("client_disconnected_mid_stream")
                    status = "cancelled"
                    return
                if event["type"] == "usage":
                    input_tokens = event["inputTokens"]
                    output_tokens = event["outputTokens"]
                yield _sse(event)
        except AppError as exc:
            status = "failed"
            log.warning("chat_stream_app_error", detail=exc.detail)
            yield _sse({"type": "error", "message": exc.detail})
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            log.error("chat_stream_unhandled", exc_type=type(exc).__name__, exc_info=True)
            yield _sse({"type": "error", "message": str(exc)})
        finally:
            if status == "succeeded":
                try:
                    await record_usage(
                        session,
                        provider=provider_name,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        conversation_id=body.conversation_id,
                    )
                except Exception:  # noqa: BLE001
                    log.warning("usage_persist_failed", exc_info=True)
            yield _sse({"type": "done", "status": status})

    return EventSourceResponse(generator())
