"""Small cross-module helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, MutableMapping
from datetime import datetime, timezone
from typing import Generic, TypeVar
from weakref import WeakKeyDictionary

T = TypeVar("T")


def to_ms(dt: datetime) -> int:
    """Convert a (possibly naive) datetime to Unix milliseconds, treating naive as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class LoopLocal(Generic[T]):
    """A value built once per event loop.

    `asyncio` primitives (`Lock`, `Semaphore`) bind themselves to the loop that first
    awaits them and raise if they are then used from another one. Production runs a single
    loop for the process lifetime, so a module-level primitive would be fine there — but
    the test suite gives every test its own loop (`asyncio_mode = auto`), which would turn
    any process-wide primitive into a cross-test landmine. Keying by the running loop keeps
    module-level state without that trap; entries are weak, so a finished loop's value goes
    away with it.
    """

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._values: MutableMapping[asyncio.AbstractEventLoop, T] = WeakKeyDictionary()

    def get(self) -> T:
        loop = asyncio.get_running_loop()
        value = self._values.get(loop)
        if value is None:
            value = self._values[loop] = self._factory()
        return value
