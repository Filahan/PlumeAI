"""structlog configuration: JSON output, contextvars binding, exception tracebacks inline."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Initialize structlog + stdlib logging so everything funnels through JSON output."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logs (uvicorn, sqlalchemy, …) through structlog as well so we get JSON
    # output consistently. uvicorn's default formatter is replaced.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    # Silence uvicorn access logs in favor of our own request middleware.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Public accessor matching the typical structlog usage pattern."""
    return structlog.get_logger(name)
