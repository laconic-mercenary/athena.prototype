"""POST /engagements — start a new run.
GET  /engagements/{run_id} — status of a run.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from athena.server import limits, runner

###############
# CONSTS / GLOBALS #
###############

router = APIRouter(prefix="/engagements")


###############
# CUSTOM TYPES #
###############

class StartEngagementRequest(BaseModel):
    instructions: str = Field(..., min_length=1, max_length=limits.MAX_INSTRUCTIONS_LEN)


class StartEngagementResponse(BaseModel):
    run_id: str


class EngagementStatusResponse(BaseModel):
    run_id: str
    status: str


###############
# FUNCTIONS #
###############

@router.post("", response_model=StartEngagementResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_engagement(body: StartEngagementRequest, request: Request) -> StartEngagementResponse:
    try:
        run_id = runner.start_engagement(body.instructions)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return StartEngagementResponse(run_id=run_id)


@router.get("/{run_id}", response_model=EngagementStatusResponse)
async def get_engagement(run_id: str) -> EngagementStatusResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return EngagementStatusResponse(run_id=run_id, status=ctx.status)


@router.post("/{run_id}/abort", status_code=status.HTTP_204_NO_CONTENT)
async def abort_engagement(run_id: str) -> None:
    """Abandon a run and free the worker so a fresh engagement can start (demo Restart).
    Idempotent — a missing/already-finished engagement is a no-op success."""
    runner.abort_engagement(run_id)
