"""GET /engagements/{run_id}/events — SSE stream of pipeline events."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from athena import engagement_status, topics
from athena.server import bus, runner

###############
# CONSTS / GLOBALS #
###############

router = APIRouter(prefix="/engagements")

# Topics that signal the engagement is finished; the SSE stream closes after either.
_TERMINAL_TOPICS = frozenset({topics.ENGAGEMENT_COMPLETED, topics.ENGAGEMENT_REJECTED})

# Engagement statuses that mean the run is already over. A client that (re)connects at
# this point missed the live terminal event — SSE has no replay — so we synthesise it.
_TERMINAL_STATUSES = engagement_status.TERMINAL

# Seconds between keepalive comments when no events are queued.
_HEARTBEAT_INTERVAL = 15


###############
# FUNCTIONS #
###############

@router.get("/{run_id}/events")
async def events_stream(run_id: str) -> StreamingResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")

    async def generate():
        # If the run already finished, tell the client immediately and close, rather than
        # leaving it waiting on heartbeats forever. This is what lets a UI that dropped its
        # connection mid-run (e.g. a transient error) recover the final state on reconnect.
        if ctx.status in _TERMINAL_STATUSES:
            topic = topics.ENGAGEMENT_COMPLETED if ctx.status == engagement_status.COMPLETED else topics.ENGAGEMENT_REJECTED
            yield f"data: {json.dumps({'topic': topic, 'run_id': run_id})}\n\n"
            return

        q = bus.create_queue(run_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_INTERVAL)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("topic") in _TERMINAL_TOPICS:
                        break
                except asyncio.TimeoutError:
                    # SSE comment — keeps the connection alive without triggering
                    # client-side event handlers.
                    yield ": heartbeat\n\n"
        finally:
            bus.remove_queue(run_id, q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Prevents nginx from buffering the stream before sending to browser.
            "X-Accel-Buffering": "no",
        },
    )
