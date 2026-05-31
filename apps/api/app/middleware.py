"""Request logging middleware: binds request_id + path to structlog contextvars and emits
one INFO log line per completed request with status + duration."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Generate a request_id, bind it to structlog contextvars, log timing on completion."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=rid,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The global exception handler will log + respond. We just re-raise.
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log.error("request_failed", duration_ms=duration_ms)
            raise
        else:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            response.headers["x-request-id"] = rid
            log.info(
                "request_completed",
                status=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()
