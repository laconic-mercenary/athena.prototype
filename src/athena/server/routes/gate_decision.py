"""POST /engagements/{run_id}/gate-decision — operator-authoritative committee gate.

When a committee finishes at an operator_approval gate, the operator decides the
transition directly: "accept" (advance) or "redo" (re-run the committee with an
optional suggestion). This replaces the old approve/reject; the orchestrator does
not decide a gated committee. See projects/202607/BRIEFING.md (Architecture X).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from athena.server import runner

router = APIRouter(prefix="/engagements")

_MAX_SUGGESTION_LEN = 2000


class GateDecisionRequest(BaseModel):
    action: str = Field(..., description='"accept" or "redo"')
    suggestion: str | None = Field(default=None, max_length=_MAX_SUGGESTION_LEN)


class GateDecisionResponse(BaseModel):
    action: str


@router.post("/{run_id}/gate-decision", response_model=GateDecisionResponse)
async def gate_decision(run_id: str, body: GateDecisionRequest) -> GateDecisionResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not ctx.awaiting_approval:
        raise HTTPException(status_code=409, detail="Pipeline is not currently awaiting a gate decision")

    action = body.action.strip().lower()
    if action not in ("accept", "redo"):
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'redo'")

    try:
        runner.resolve_gate_decision(run_id, action=action, suggestion=body.suggestion)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return GateDecisionResponse(action=action)
