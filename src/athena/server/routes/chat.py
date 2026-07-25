"""POST /engagements/{run_id}/chat/{target} — operator message injection.

target is either ORCHESTRATOR_AGENT_ID (routes to orchestrator ask_user reply)
or a committee name (routes to that committee's leader queue).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from athena.server import runner
from athena.server.runner import ORCHESTRATOR_AGENT_ID

router = APIRouter(prefix="/engagements")

_MAX_MESSAGE_LEN = 2000


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_LEN)


@router.post("/{run_id}/chat/{target}", status_code=204)
async def send_message(run_id: str, target: str, body: ChatRequest) -> None:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if ctx.status != "running":
        raise HTTPException(status_code=409, detail="Engagement is not currently running")

    if target == ORCHESTRATOR_AGENT_ID:
        if ctx.awaiting_approval:
            # Plan is submitted and awaiting approval — treat as revision request.
            try:
                runner.request_revision(run_id, body.message)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc))
            return
        if ctx.pending_question is None:
            raise HTTPException(status_code=400, detail="Orchestrator has no pending question")
        try:
            runner.reply_to_orchestrator(run_id, body.message)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return

    # Otherwise treat target as a committee name
    try:
        runner.send_to_leader(run_id, target, body.message)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"No active leader for committee {target!r}",
        )
