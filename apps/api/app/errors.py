"""Error hierarchy + RFC 7807 Problem Details handler.

Every error response from the API conforms to https://datatracker.ietf.org/doc/html/rfc7807
so the frontend can render consistent toasts and the request_id allows correlation with logs.
"""

from __future__ import annotations

import traceback
from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger("app.errors")

PROBLEM_BASE = "https://plumeai.local/errors"


class AppError(Exception):
    """Base class for known, expected errors. Subclasses set status_code + title."""

    status_code: int = 500
    title: str = "Internal error"
    type_slug: str = "internal-error"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}

    def to_problem(self, instance: str, request_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"{PROBLEM_BASE}/{self.type_slug}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
            "instance": instance,
        }
        if request_id:
            body["request_id"] = request_id
        if self.extra:
            body["extra"] = self.extra
        return body


class NotFound(AppError):
    status_code = 404
    title = "Not found"
    type_slug = "not-found"


class Unauthorized(AppError):
    status_code = 401
    title = "Unauthorized"
    type_slug = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    title = "Forbidden"
    type_slug = "forbidden"


class BadRequest(AppError):
    status_code = 400
    title = "Bad request"
    type_slug = "bad-request"


class ValidationFailure(AppError):
    status_code = 422
    title = "Validation failed"
    type_slug = "validation-failed"


class ProviderError(AppError):
    status_code = 502
    title = "Upstream provider error"
    type_slug = "provider-error"


class ToolError(AppError):
    status_code = 500
    title = "Tool execution failed"
    type_slug = "tool-error"


class ToolNotConfigured(AppError):
    status_code = 412
    title = "Tool not configured"
    type_slug = "tool-not-configured"


def _request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id") or getattr(request.state, "request_id", None)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    rid = _request_id(request)
    log.warning(
        "app_error",
        status=exc.status_code,
        type=exc.type_slug,
        detail=exc.detail,
        path=request.url.path,
        request_id=rid,
        **exc.extra,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_problem(instance=request.url.path, request_id=rid),
        headers={"Content-Type": "application/problem+json"},
    )


async def starlette_http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    rid = _request_id(request)
    body = {
        "type": f"{PROBLEM_BASE}/http-{exc.status_code}",
        "title": exc.detail if isinstance(exc.detail, str) else "HTTP error",
        "status": exc.status_code,
        "detail": exc.detail if isinstance(exc.detail, str) else "",
        "instance": request.url.path,
    }
    if rid:
        body["request_id"] = rid
    log.info("http_error", status=exc.status_code, detail=exc.detail, request_id=rid)
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers={"Content-Type": "application/problem+json"},
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    rid = _request_id(request)
    body = {
        "type": f"{PROBLEM_BASE}/validation-failed",
        "title": "Validation failed",
        "status": 422,
        "detail": "Request body did not match the expected schema.",
        "instance": request.url.path,
        "errors": exc.errors(),
    }
    if rid:
        body["request_id"] = rid
    log.info("validation_error", errors=exc.errors(), request_id=rid)
    return JSONResponse(
        status_code=422, content=body, headers={"Content-Type": "application/problem+json"}
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = _request_id(request)
    log.error(
        "unhandled_error",
        exc_type=type(exc).__name__,
        exc_message=str(exc),
        stack=traceback.format_exc(),
        path=request.url.path,
        request_id=rid,
    )
    body = {
        "type": f"{PROBLEM_BASE}/internal-error",
        "title": "Internal error",
        "status": 500,
        "detail": "Something went wrong on the server. The error has been logged.",
        "instance": request.url.path,
    }
    if rid:
        body["request_id"] = rid
    return JSONResponse(
        status_code=500, content=body, headers={"Content-Type": "application/problem+json"}
    )


def register_handlers(app: Any) -> None:
    """Register all exception handlers on the FastAPI app."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, starlette_http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
