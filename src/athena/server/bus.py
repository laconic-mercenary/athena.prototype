"""PyPubSub → asyncio.Queue bridge for SSE events.

The pipeline runs in a ThreadPoolExecutor (a non-async thread). PyPubSub
fires synchronously on that thread. This bridge catches every published
message and pushes it into a per-engagement asyncio.Queue so the SSE
handler (running in the event loop) can drain it without blocking.

call_soon_threadsafe is used to safely cross the thread→event-loop boundary.
"""

from __future__ import annotations

import asyncio

from pubsub import pub

# Set once at server startup; never mutated thereafter.
_loop: asyncio.AbstractEventLoop | None = None

# One queue per active engagement, keyed by run_id. Created when the SSE
# stream opens; removed when it closes. Not persistent — see WORKSPACE_TODO.md.
_queues: dict[str, asyncio.Queue] = {}


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Bind the running event loop. Must be called before any pipeline starts."""
    global _loop
    _loop = loop


def create_queue(run_id: str) -> asyncio.Queue:
    """Create and register an event queue for a new SSE connection."""
    q: asyncio.Queue = asyncio.Queue()
    _queues[run_id] = q
    return q


def remove_queue(run_id: str, q: asyncio.Queue) -> None:
    """Remove the queue only if it is still the one we registered.

    Guarded by identity check to avoid a race where a new SSE connection
    creates a replacement queue before the old generator's finally block runs.
    """
    if _queues.get(run_id) is q:
        del _queues[run_id]


def _bridge(topicObj=pub.AUTO_TOPIC, **kwargs) -> None:
    """PyPubSub listener — receives every published message on the pipeline thread."""
    if _loop is None:
        return
    run_id = kwargs.get("run_id")
    if not run_id:
        return
    q = _queues.get(run_id)
    if q is not None:
        event = {"topic": topicObj.getName(), **kwargs}
        _loop.call_soon_threadsafe(q.put_nowait, event)


pub.subscribe(_bridge, pub.ALL_TOPICS)
