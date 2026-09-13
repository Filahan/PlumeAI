"""Tool dispatch: routes a tool-call name to either a builtin or an integration."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError, ToolError
from app.integrations.registry import (
    find_integration_for_function,
    list_configured_integrations,
)
from app.tools.base import ToolResult, safe_json_args
from app.tools.builtin import BUILTIN_DISPATCH, BUILTIN_NAMES, BUILTIN_SCHEMAS

log = structlog.get_logger("app.tools.registry")


def builtin_tool_schemas() -> list[dict[str, Any]]:
    """The always-on built-in tool schemas (web_search, web_fetch, http)."""
    return list(BUILTIN_SCHEMAS)


async def list_available_tool_schemas(session: AsyncSession) -> list[dict[str, Any]]:
    """Built-ins + all integrations the user has currently connected."""
    schemas: list[dict[str, Any]] = list(BUILTIN_SCHEMAS)
    for integ in await list_configured_integrations(session):
        schemas.extend(integ.schemas)
    return schemas


def _is_retryable(exc: AppError) -> bool:
    """Whether another attempt of a tool call that raised `exc` could do better.

    A bare `ToolError` is the generic runtime failure (a timeout, an upstream hiccup) and
    is worth retrying unless it says otherwise. Every *other* `AppError` — a disconnected
    integration (`ToolNotConfigured`), a bad argument (`BadRequest`), a missing resource
    (`NotFound`) — is the tool rejecting the request, which it will do identically next
    time. `extra={"retryable": False}` lets a `ToolError` opt out (the SSRF guard does).
    """
    if not isinstance(exc, ToolError):
        return False
    return bool(exc.extra.get("retryable", True))


async def execute_tool(name: str, raw_args: str, session: AsyncSession) -> ToolResult:
    """Dispatch a tool call. Errors are wrapped into a failed `ToolResult` so the agent
    loop can feed the error back to the LLM rather than killing the stream.

    A failed result also carries `retryable`, which is what the automation executor reads
    to decide whether to spend another attempt on the step (see `_is_retryable`).
    """
    args = safe_json_args(raw_args)
    try:
        if name in BUILTIN_NAMES:
            return await BUILTIN_DISPATCH[name](args)
        integ = find_integration_for_function(name)
        if integ is not None:
            return await integ.execute(name, args, session)
        return ToolResult(ok=False, content=f"Unknown tool: {name}", retryable=False)
    except AppError as exc:
        retryable = _is_retryable(exc)
        log.warning(
            "tool_error",
            tool=name,
            exc_type=type(exc).__name__,
            retryable=retryable,
            exc_info=True,
        )
        return ToolResult(ok=False, content=f"Error: {exc.detail}", retryable=retryable)
    except Exception as exc:  # noqa: BLE001
        log.warning("tool_error", tool=name, exc_type=type(exc).__name__, exc_info=True)
        return ToolResult(ok=False, content=f"Error: {exc}")
