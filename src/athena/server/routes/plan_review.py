"""POST /engagements/{run_id}/plan-review — plan approval gate.

The UI sends "approve" or "reject" to release the gate that blocks the
pipeline after the orchestrator's submit_plan() call.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from athena.server import runner

router = APIRouter(prefix="/engagements")


class PlanReviewRequest(BaseModel):
    action: str   # "approve" | "reject"


class PlanReviewResponse(BaseModel):
    action: str   # echoed back


@router.post("/{run_id}/plan-review", response_model=PlanReviewResponse)
async def plan_review(run_id: str, body: PlanReviewRequest) -> PlanReviewResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not ctx.awaiting_approval:
        raise HTTPException(status_code=409, detail="Pipeline is not currently awaiting approval")

    action = body.action.strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    approved = action == "approve"
    try:
        runner.resolve_approval(run_id, approved=approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return PlanReviewResponse(action=action)
