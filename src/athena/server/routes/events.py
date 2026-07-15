"""GET /engagements/{run_id}/events — SSE stream of pipeline events."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from athena.server import bus, runner

router = APIRouter(prefix="/engagements")

# Topics that signal the engagement is finished; the SSE stream closes after either.
_TERMINAL_TOPICS = frozenset({"engagement.completed", "engagement.rejected"})

# Seconds between keepalive comments when no events are queued.
_HEARTBEAT_INTERVAL = 15


@router.get("/{run_id}/events")
async def events_stream(run_id: str) -> StreamingResponse:
    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

    async def generate():
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
