"""
Minimal per-decision pub/sub so multiple SSE clients (or a reconnecting
client) can subscribe to the same running graph execution. Each decision_id
gets its own asyncio.Queue; the graph runner pushes events into it as
node functions append to state["events"], and the SSE route drains it.

This is intentionally in-process and not durable — fine for a single backend
instance in a hackathon deploy. If you scale to multiple backend replicas,
swap this for a Redis pub/sub channel keyed by decision_id.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

_queues: dict[str, asyncio.Queue] = {}

_SENTINEL = object()


def create_channel(decision_id: str) -> None:
    _queues[decision_id] = asyncio.Queue()


def publish(decision_id: str, event: dict) -> None:
    queue = _queues.get(decision_id)
    if queue is not None:
        queue.put_nowait(event)


def close_channel(decision_id: str) -> None:
    queue = _queues.get(decision_id)
    if queue is not None:
        queue.put_nowait(_SENTINEL)


async def subscribe(decision_id: str) -> AsyncIterator[str]:
    """Yields SSE-formatted strings until the channel is closed."""
    queue = _queues.setdefault(decision_id, asyncio.Queue())
    try:
        while True:
            event = await queue.get()
            if event is _SENTINEL:
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"
    finally:
        pass  # keep the queue around briefly in case of client reconnect; a
        # production version would TTL-evict channels after N minutes idle.
