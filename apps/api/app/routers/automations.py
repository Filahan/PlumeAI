"""Automations: CRUD + interview chat + run (SSE)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agent.runner import stream_agent
from app.auth import CurrentUser
from app.db.base import get_session
from app.errors import AppError
from app.llm.base import ChatMessage
from app.llm.factory import get_provider_for
from app.schemas.automations import (
    ChatTaskRequest,
    ChatTaskResponse,
    CreateTaskRequest,
    RunTaskRequest,
    TaskPayload,
    TaskRun,
    UpdateTaskRequest,
)
from app.services import automations as svc
from app.services.interview import generate_task_title, interview
from app.services.usage import record_usage
from app.tools.registry import list_available_tool_schemas

router = APIRouter(prefix="/automations", tags=["automations"])
log = structlog.get_logger("app.automations")

DBSession = Annotated[AsyncSession, Depends(get_session)]


# ─── CRUD ────────────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[TaskPayload], response_model_by_alias=True)
async def list_tasks_route(user: CurrentUser, session: DBSession) -> list[TaskPayload]:
    return await svc.list_tasks(session)


@router.post("", response_model=TaskPayload, response_model_by_alias=True)
async def create_task_route(
    body: CreateTaskRequest, user: CurrentUser, session: DBSession
) -> TaskPayload:
    return await svc.create_task(session, body)


@router.patch("/{task_id}", response_model=TaskPayload, response_model_by_alias=True)
async def update_task_route(
    task_id: str, body: UpdateTaskRequest, user: CurrentUser, session: DBSession
) -> TaskPayload:
    return await svc.update_task(session, task_id, body)


@router.delete("/{task_id}")
async def delete_task_route(
    task_id: str, user: CurrentUser, session: DBSession
) -> dict[str, str]:
    await svc.delete_task(session, task_id)
    return {"status": "ok"}


# ─── Interview chat ──────────────────────────────────────────────────────────────────


@router.post(
    "/chat", response_model=ChatTaskResponse, response_model_by_alias=True, response_model_exclude_none=True
)
async def chat_route(
    body: ChatTaskRequest, user: CurrentUser, session: DBSession
) -> ChatTaskResponse:
    task = await svc.get_task(session, body.task_id)
    history = list(task.messages or [])
    is_first = len(history) == 0

    # Interview + title generation run in parallel — first-exchange overhead is minimal.
    interview_coro = interview(
        session,
        provider=task.provider,
        model=task.model,
        history=history,
        user_message=body.message,
    )
    title_coro: asyncio.Future[str] | asyncio.Task[str]
    if is_first and not task.title:
        title_coro = asyncio.create_task(
            generate_task_title(session, task.provider, task.model, body.message)
        )
    else:
        f: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        f.set_result(task.title or "")
        title_coro = f

    result = await interview_coro
    generated_title = await title_coro

    user_msg = {"role": "user", "content": body.message}
    if result.kind == "ask":
        asst_msg: dict[str, object] = {"role": "assistant", "content": result.question}
        if result.options:
            asst_msg["options"] = result.options
        new_messages = [user_msg, asst_msg]
        await svc.append_messages(
            session,
            body.task_id,
            new_messages,  # type: ignore[arg-type]
            title=generated_title if generated_title and not task.title else None,
        )
        resp = ChatTaskResponse(question=result.question, options=result.options)
    else:
        new_messages = [user_msg, {"role": "assistant", "content": "Skill ready."}]
        await svc.append_messages(
            session,
            body.task_id,
            new_messages,  # type: ignore[arg-type]
            prompt=result.skill,
            title=generated_title if generated_title and not task.title else None,
        )
        resp = ChatTaskResponse(finalized=True, skill=result.skill)

    if generated_title and not task.title:
        resp.title = generated_title
    return resp


# ─── Run (SSE) ───────────────────────────────────────────────────────────────────────


def _sse(event: dict) -> dict:
    return {"data": json.dumps(event, separators=(",", ":"))}


RUN_SYSTEM_PROMPT_TEMPLATE = (
    "Today's date is {today}. When the task mentions 'today', 'yesterday', 'last week', "
    "etc., resolve them to concrete dates yourself before calling tools. For Gmail "
    "searches specifically, the date format Gmail expects is YYYY/MM/DD (e.g. "
    "`after:{today_slash}`) — never pass the literal word 'today' to the Gmail API.\n\n"
    "You are an automation agent. Use the available tools to actually accomplish the task — "
    "search the web, read pages, call HTTP APIs (GET/POST/PUT/PATCH/DELETE), or use any "
    "connected integration tools (e.g. Gmail) — rather than saying you cannot. "
    "When the task is complete, reply with only the final result."
)


def _build_run_system_prompt() -> str:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return RUN_SYSTEM_PROMPT_TEMPLATE.format(today=today, today_slash=today.replace("-", "/"))


@router.post("/run")
async def run_route(
    body: RunTaskRequest, request: Request, user: CurrentUser, session: DBSession
) -> EventSourceResponse:
    task = await svc.get_task(session, body.task_id)
    if not task.prompt or not task.prompt.strip():
        from app.errors import BadRequest

        raise BadRequest("Task has no skill prompt to run. Finalize the interview first.")

    provider_name = task.provider
    model = task.model
    skill = task.prompt
    conversation_id = task.id

    provider = await get_provider_for(session, provider_name)
    tools = await list_available_tool_schemas(session)

    # Mark running.
    task.status = "running"
    task.output = ""
    task.transcript = []
    task.error = None
    await session.flush()

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=_build_run_system_prompt()),
        ChatMessage(role="user", content=skill),
    ]

    async def generator() -> AsyncIterator[dict]:
        started_at = int(time.time() * 1000)
        assistant_buf = ""
        transcript: list[dict] = []
        idx_by_id: dict[str, int] = {}
        input_tokens = 0
        output_tokens = 0
        status = "succeeded"
        error: str | None = None

        try:
            async for event in stream_agent(
                provider=provider,
                model=model,
                messages=messages,
                tools=tools,
                session=session,
            ):
                if await request.is_disconnected():
                    log.info("client_disconnected_mid_run", task_id=conversation_id)
                    status = "cancelled"
                    return

                t = event["type"]
                if t == "text":
                    assistant_buf += event["delta"]
                elif t == "tool_call":
                    if assistant_buf:
                        transcript.append({"kind": "assistant", "text": assistant_buf})
                        assistant_buf = ""
                    idx = len(transcript)
                    idx_by_id[event["id"]] = idx
                    transcript.append(
                        {
                            "kind": "tool",
                            "tool": event["tool"],
                            "args": event["args"],
                            "result": "",
                            "ok": True,
                        }
                    )
                elif t == "tool_result":
                    idx = idx_by_id.get(event["id"])
                    if idx is not None:
                        transcript[idx]["result"] = event["result"]
                        transcript[idx]["ok"] = event["ok"]
                elif t == "final":
                    if assistant_buf and (
                        not transcript or transcript[-1].get("kind") == "tool"
                    ):
                        transcript.append({"kind": "assistant", "text": assistant_buf})
                    assistant_buf = event["text"] or assistant_buf
                elif t == "usage":
                    input_tokens = event["inputTokens"]
                    output_tokens = event["outputTokens"]
                elif t == "error":
                    status = "failed"
                    error = event["message"]
                yield _sse(event)
        except AppError as exc:
            status = "failed"
            error = exc.detail
            log.warning("run_app_error", task_id=conversation_id, detail=exc.detail)
            yield _sse({"type": "error", "message": exc.detail})
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = str(exc)
            log.error("run_unhandled", task_id=conversation_id, exc_info=True)
            yield _sse({"type": "error", "message": error})
        finally:
            ended_at = int(time.time() * 1000)
            run = TaskRun(
                status=status if status in {"succeeded", "failed", "cancelled"} else "failed",
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=ended_at - started_at,
                error=error,
            )
            try:
                await svc.append_run(
                    session,
                    conversation_id,
                    run=run,
                    output=assistant_buf,
                    transcript=transcript,
                    status=status,
                    error=error,
                )
                if status == "succeeded":
                    await record_usage(
                        session,
                        provider=provider_name,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except Exception:  # noqa: BLE001
                log.warning("run_persist_failed", task_id=conversation_id, exc_info=True)
            yield _sse({"type": "done", "status": status})

    return EventSourceResponse(generator())
