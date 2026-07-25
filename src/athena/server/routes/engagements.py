"""POST /engagements — start a new run.
GET  /engagements/{run_id} — status of a run.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from athena.server import runner

router = APIRouter(prefix="/engagements")

_MAX_INSTRUCTIONS_LEN = 8192


class StartEngagementRequest(BaseModel):
    instructions: str = Field(..., min_length=1, max_length=_MAX_INSTRUCTIONS_LEN)


class StartEngagementResponse(BaseModel):
    run_id: str


class EngagementStatusResponse(BaseModel):
    run_id: str
    status: str


@router.post("", response_model=StartEngagementResponse, status_code=202)
async def start_engagement(body: StartEngagementRequest, request: Request) -> StartEngagementResponse:
    try:
        run_id = runner.start_engagement(body.instructions)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return StartEngagementResponse(run_id=run_id)


@router.get("/{run_id}", response_model=EngagementStatusResponse)
async def get_engagement(run_id: str) -> EngagementStatusResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return EngagementStatusResponse(run_id=run_id, status=ctx.status)
