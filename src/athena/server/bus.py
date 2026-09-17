"""PyPubSub → asyncio.Queue bridge for SSE events.

The pipeline runs on a background thread (one per engagement). PyPubSub
fires synchronously on that thread. This bridge catches every published
message and pushes it into a per-engagement asyncio.Queue so the SSE
handler (running in the event loop) can drain it without blocking.

call_soon_threadsafe is used to safely cross the thread→event-loop boundary.
"""

from __future__ import annotations

import asyncio
import logging

from pubsub import pub


###############
# CONSTS / GLOBALS #
###############

_log = logging.getLogger("athena.server.bus")

# Set once at server startup; never mutated thereafter.
_loop: asyncio.AbstractEventLoop | None = None

# One SET of queues per active engagement, keyed by run_id — a single run can feed several
# open SSE streams at once (e.g. an animating projects-view row plus a drilled-in dashboard).
# A queue is added when a stream opens; the run_id key is dropped once its last stream closes.
_queues: dict[str, set[asyncio.Queue]] = {}


###############
# FUNCTIONS #
###############

def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Bind the running event loop. Must be called before any pipeline starts."""
    global _loop
    _loop = loop


def create_queue(run_id: str) -> asyncio.Queue:
    """Create and register an event queue for a new SSE connection."""
    q: asyncio.Queue = asyncio.Queue()
    _queues.setdefault(run_id, set()).add(q)
    return q


def remove_queue(run_id: str, q: asyncio.Queue) -> None:
    """Deregister a closed SSE connection's queue, dropping the run_id key once its last
    stream closes. create_queue and remove_queue both run on the event-loop thread, so they
    never race each other; _bridge (harness thread) only reads the set."""
    queues = _queues.get(run_id)
    if queues is None:
        _log.warning("remove_queue called for run_id %r with no registered queues", run_id)
        return
    queues.discard(q)
    if not queues:
        _queues.pop(run_id, None)


###############
# NON PUBLIC FUNCTIONS #
###############

def _bridge(topicObj=pub.AUTO_TOPIC, **kwargs) -> None:
    """PyPubSub listener — receives every published message on the pipeline thread."""
    if _loop is None:
        return
    run_id = kwargs.get("run_id")
    if not run_id:
        return
    queues = _queues.get(run_id)
    if not queues:
        return
    event = {"topic": topicObj.getName(), **kwargs}
    # Snapshot the set: this runs on the harness thread while create/remove_queue mutate on
    # the event-loop thread. list() copies under the GIL without yielding, so no listener is
    # added or dropped mid-iteration; a queue removed just after the copy gets one ignored event.
    for q in list(queues):
        _loop.call_soon_threadsafe(q.put_nowait, event)


pub.subscribe(_bridge, pub.ALL_TOPICS)
