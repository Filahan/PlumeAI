"""Pub/sub semantics of `app.services.run_events` (no DB involved)."""

from __future__ import annotations

import asyncio

import pytest

from app.services import run_events


@pytest.fixture(autouse=True)
def _clean_topics():
    """Topics are module-level state; make sure a test never inherits another's."""
    run_events._subscribers.clear()
    yield
    run_events._subscribers.clear()


async def test_publish_reaches_every_subscriber() -> None:
    a = run_events.subscribe("run1")
    b = run_events.subscribe("run1")
    other = run_events.subscribe("run2")

    run_events.publish("run1", {"type": "step_started", "stepId": "step_abcde"})

    assert (await a.get())["type"] == "step_started"
    assert (await b.get())["type"] == "step_started"
    assert other.empty()


async def test_publish_with_no_subscribers_is_a_noop() -> None:
    run_events.publish("nobody-listening", {"type": "step_started"})
    assert run_events.subscriber_count("nobody-listening") == 0


async def test_unsubscribe_stops_delivery_and_is_idempotent() -> None:
    queue = run_events.subscribe("run1")
    run_events.unsubscribe("run1", queue)
    run_events.unsubscribe("run1", queue)  # second call must not raise

    run_events.publish("run1", {"type": "step_started"})
    assert queue.empty()
    assert run_events.subscriber_count("run1") == 0


async def test_close_pushes_the_sentinel_and_drops_subscribers() -> None:
    a = run_events.subscribe("run1")
    b = run_events.subscribe("run1")

    run_events.publish("run1", {"type": "run_finished"})
    run_events.close("run1")

    assert (await a.get())["type"] == "run_finished"
    assert await a.get() is run_events.SENTINEL
    assert await b.get() == {"type": "run_finished"}
    assert await b.get() is run_events.SENTINEL

    # The topic is gone: later publishes reach nobody, and unsubscribe still works.
    assert run_events.subscriber_count("run1") == 0
    run_events.publish("run1", {"type": "late"})
    assert a.empty()
    run_events.unsubscribe("run1", a)


async def test_bounded_queue_drops_the_oldest_events() -> None:
    queue = run_events.subscribe("run1")
    overflow = run_events.MAX_QUEUE + 5
    for i in range(overflow):
        run_events.publish("run1", {"type": "tick", "i": i})

    assert queue.qsize() == run_events.MAX_QUEUE
    # The oldest 5 were evicted; the newest are the ones that survived.
    assert (await queue.get())["i"] == overflow - run_events.MAX_QUEUE
    while queue.qsize() > 1:
        await queue.get()
    assert (await queue.get())["i"] == overflow - 1


async def test_close_delivers_the_sentinel_even_to_a_full_queue() -> None:
    queue = run_events.subscribe("run1")
    for i in range(run_events.MAX_QUEUE):
        run_events.publish("run1", {"type": "tick", "i": i})
    assert queue.full()

    run_events.close("run1")

    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert items[-1] is run_events.SENTINEL


async def test_a_waiting_consumer_is_woken_by_publish() -> None:
    queue = run_events.subscribe("run1")
    task = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    run_events.publish("run1", {"type": "step_started"})
    assert (await asyncio.wait_for(task, timeout=1))["type"] == "step_started"
