"""POST /engagements/{run_id}/plan-review — plan approval gate.

When COLLABORATION_ENABLED and the request carries a collaborator alias, the
gate stays blocked while an approval email is sent to the collaborator. The
inbound webhook (routes/collaboration.py) releases it when the reply arrives.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from pubsub import pub

from athena import topics

from athena import collaboration
from athena.server import runner

###############
# CONSTS / GLOBALS #
###############

_log = logging.getLogger("athena.server.routes.plan_review")

router = APIRouter(prefix="/engagements")


###############
# CUSTOM TYPES #
###############

class PlanReviewRequest(BaseModel):
    action: str                    # "approve" | "reject"
    collaborator: str | None = None  # "@alias" — triggers collaboration flow on approve
    plan_text: str | None = None     # forwarded verbatim in the collaboration email


class PlanReviewResponse(BaseModel):
    action: str   # echoed back, or "collaborator_pending"


###############
# FUNCTIONS #
###############

@router.post("/{run_id}/plan-review", response_model=PlanReviewResponse)
async def plan_review(run_id: str, body: PlanReviewRequest) -> PlanReviewResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    if ctx.await_phase != runner.AWAIT_PLAN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline is not currently awaiting plan approval",
        )

    action = body.action.strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="action must be 'approve' or 'reject'"
        )

    if action == "approve" and body.collaborator and collaboration.COLLABORATION_ENABLED:
        alias = collaboration.extract_alias(body.collaborator)
        if not alias:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No collaborator alias provided"
            )
        email = collaboration.resolve_alias(alias)
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown collaborator alias: @{alias}",
            )
        try:
            await collaboration.send_approval_request(
                run_id=run_id,
                alias=alias,
                to_email=email,
                plan_text=body.plan_text or "",
                note=body.collaborator or "",
                context_noun="engagement plan",
                attachment_name="plan-briefing.txt",
            )
        except Exception:
            _log.exception("failed to send collaboration email for %r", run_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to send collaboration email",
            )
        state = collaboration.register(run_id, alias, email, kind="plan", committee=None)
        pub.sendMessage(
            topics.ENGAGEMENT_COLLABORATOR_PENDING,
            run_id=run_id,
            alias=alias,
            sent_at=state.sent_at.isoformat(),
        )
        return PlanReviewResponse(action="collaborator_pending")

    approved = action == "approve"
    try:
        runner.resolve_approval(run_id, approved=approved)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return PlanReviewResponse(action=action)
