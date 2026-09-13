"""In-process pub/sub for live run progress.

One topic per run id. The executor publishes `{"type": ...}` dicts; each SSE connection
watching that run holds one subscriber queue and forwards whatever lands in it. Purely
in-memory and single-process — a run's events are only visible to the worker that is
executing it, which matches the deployment (one uvicorn process owning its own runs).

Backpressure policy: queues are bounded at `MAX_QUEUE` events and **drop the oldest**
event when full. A client too slow to keep up loses early progress rather than stalling
the executor or growing the queue without bound; it always keeps the most recent events,
including the terminal `run_finished`, and the SSE endpoint's initial DB snapshot means
a reconnect resyncs the authoritative state anyway.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

import structlog

log = structlog.get_logger("app.run_events")

MAX_QUEUE: Final = 1000


class _Sentinel:
    """End-of-stream marker put on every subscriber queue by `close()`."""

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return "<run_events.SENTINEL>"


SENTINEL: Final = _Sentinel()

Event = dict[str, Any]

_subscribers: dict[str, set[asyncio.Queue[Any]]] = {}


def subscribe(run_id: str) -> asyncio.Queue[Any]:
    """Register a new subscriber queue for `run_id` and return it."""
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=MAX_QUEUE)
    _subscribers.setdefault(run_id, set()).add(queue)
    return queue


def unsubscribe(run_id: str, queue: asyncio.Queue[Any]) -> None:
    """Detach `queue`. Safe to call twice, and safe after `close()`."""
    queues = _subscribers.get(run_id)
    if queues is None:
        return
    queues.discard(queue)
    if not queues:
        _subscribers.pop(run_id, None)


def publish(run_id: str, event: Event) -> None:
    """Fan `event` out to every subscriber of `run_id`. Never blocks, never raises."""
    for queue in list(_subscribers.get(run_id, ())):
        _offer(queue, event)


def close(run_id: str) -> None:
    """End the stream: push the sentinel to every subscriber and drop the topic.

    The sentinel is delivered even to a full queue (one event is dropped to make room),
    so a subscriber can never miss end-of-stream and hang.
    """
    for queue in _subscribers.pop(run_id, set()):
        _offer(queue, SENTINEL)


def subscriber_count(run_id: str) -> int:
    """How many queues are currently attached to `run_id` (tests / diagnostics)."""
    return len(_subscribers.get(run_id, ()))


def _offer(queue: asyncio.Queue[Any], item: Any) -> None:
    """Put `item` on `queue`, evicting the oldest entry if the queue is full."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:  # pragma: no cover — another consumer drained it
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:  # pragma: no cover — lost the race with a concurrent put
            log.warning("run_event_dropped")
