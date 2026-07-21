"""POST /engagements/{run_id}/chat/{agent_id} — operator message to a pipeline agent."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from athena.server import runner
from athena.server.runner import ORCHESTRATOR_AGENT_ID

router = APIRouter(prefix="/engagements")

_MAX_MESSAGE_LEN = 2000


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_LEN)


@router.post("/{run_id}/chat/{agent_id}", status_code=204)
async def send_message(run_id: str, agent_id: str, body: ChatRequest) -> None:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if ctx.status != "running":
        raise HTTPException(status_code=409, detail="Engagement is not currently running")

    if agent_id == ORCHESTRATOR_AGENT_ID:
        if ctx.pending_question is None:
            raise HTTPException(status_code=400, detail="Orchestrator has no pending question")
        try:
            runner.reply_to_orchestrator(run_id, body.message)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return

    try:
        runner.send_to_agent(run_id, agent_id, body.message)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_id!r} is not available for chat in this engagement",
        )
