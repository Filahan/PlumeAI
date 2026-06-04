"""Small cross-module helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def to_ms(dt: datetime) -> int:
    """Convert a (possibly naive) datetime to Unix milliseconds, treating naive as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
