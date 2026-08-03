"""POST /engagements/{run_id}/gate-decision — operator-authoritative committee gate.

When a committee finishes at an operator_approval gate, the operator decides the
transition directly: "accept" (advance) or "redo" (re-run the committee with an
optional suggestion). This replaces the old approve/reject; the orchestrator does
not decide a gated committee. See projects/202607/BRIEFING.md (Architecture X).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pubsub import pub

from athena import collaboration
from athena.server import runner

_log = logging.getLogger("athena.server.routes.gate_decision")

router = APIRouter(prefix="/engagements")

_MAX_SUGGESTION_LEN = 2000


class GateDecisionRequest(BaseModel):
    action: str = Field(..., description='"accept" or "redo"')
    suggestion: str | None = Field(default=None, max_length=_MAX_SUGGESTION_LEN)
    # Accept + "@alias …" co-approves the advance: an email goes to the collaborator and
    # the gate parks until they approve (their approval is the second of two). None on the
    # normal single-operator path.
    collaborator: str | None = Field(default=None, max_length=_MAX_SUGGESTION_LEN)


class GateDecisionResponse(BaseModel):
    action: str


@router.post("/{run_id}/gate-decision", response_model=GateDecisionResponse)
async def gate_decision(run_id: str, body: GateDecisionRequest) -> GateDecisionResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if ctx.await_phase != runner.AWAIT_COMMITTEE_GATE:
        raise HTTPException(status_code=409, detail="Pipeline is not currently awaiting a gate decision")

    action = body.action.strip().lower()
    if action not in ("accept", "redo"):
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'redo'")

    # Co-approval: Accept + "@alias" parks the gate for a collaborator instead of advancing.
    # The textbox is shared with Redo, so an Accept whose text has no "@" is just a discarded
    # note — advance normally. Advancing via co-approval takes two approvals: the operator's
    # (this click) and the collaborator's (their email reply / link), which releases "accept".
    if (
        action == "accept"
        and body.collaborator
        and "@" in body.collaborator
        and collaboration.COLLABORATION_ENABLED
    ):
        alias = collaboration.extract_alias(body.collaborator)
        if not alias:
            raise HTTPException(status_code=400, detail="No collaborator alias provided")
        email = collaboration.resolve_alias(alias)
        if email is None:
            raise HTTPException(status_code=400, detail=f"Unknown collaborator alias: @{alias}")
        committee = ctx.gate_committee or "committee"
        try:
            await collaboration.send_approval_request(
                run_id=run_id,
                alias=alias,
                to_email=email,
                plan_text=ctx.gate_digest or "",
                note=body.collaborator,
                context_noun=f"{committee} committee result",
                attachment_name="engagement-summary.txt",
            )
        except Exception:
            _log.exception("failed to send committee-gate collaboration email for %r", run_id)
            raise HTTPException(status_code=502, detail="Failed to send collaboration email")
        state = collaboration.register(run_id, alias, email, kind="committee")
        pub.sendMessage(
            "engagement.collaborator_pending",
            run_id=run_id,
            alias=alias,
            sent_at=state.sent_at.isoformat(),
        )
        return GateDecisionResponse(action="collaborator_pending")

    try:
        runner.resolve_gate_decision(run_id, action=action, suggestion=body.suggestion)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return GateDecisionResponse(action=action)
