"""In-loop operator gates — the gate family that fires *inside* a leader's turn.

Two endpoints (see projects/202607/HARNESS.md):

- POST /engagements/{run_id}/loop-gate-decision — release a pending in-loop gate.
  action is kind-specific: for an element gate, "accept" / "override" (with
  winner_id) / "redo".
- POST /engagements/{run_id}/loop-gate-arm — arm / disarm a gate kind for a
  committee. This is a runtime observation mode; it is deliberately NOT routed
  through the orchestrator plan (unlike briefing switches).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from athena.server import runner

router = APIRouter(prefix="/engagements")

_GATE_KINDS = ("element", "step", "tool")
_MAX_ID_LEN = 200


_MAX_SUGGESTION_LEN = 2000


class LoopGateDecisionRequest(BaseModel):
    action: str = Field(..., description='e.g. "accept" / "override" / "redo" / "approve" / "deny"')
    winner_id: str | None = Field(default=None, max_length=_MAX_ID_LEN)      # element override
    suggestion: str | None = Field(default=None, max_length=_MAX_SUGGESTION_LEN)  # step redo / tool deny reason


class LoopGateDecisionResponse(BaseModel):
    action: str


class LoopGateArmRequest(BaseModel):
    committee: str = Field(..., min_length=1, max_length=_MAX_ID_LEN)
    kind: str = Field(..., description='"element" | "step" | "tool"')
    armed: bool


class LoopGateArmResponse(BaseModel):
    committee: str
    kind: str
    armed: bool


@router.post("/{run_id}/loop-gate-decision", response_model=LoopGateDecisionResponse)
async def loop_gate_decision(
    run_id: str, body: LoopGateDecisionRequest
) -> LoopGateDecisionResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if ctx.await_phase != runner.AWAIT_LOOP_GATE:
        raise HTTPException(
            status_code=409, detail="Pipeline is not currently awaiting an in-loop gate decision"
        )

    action = body.action.strip().lower()
    payload: dict = {}
    if body.winner_id is not None:
        payload["winner_id"] = body.winner_id
    if body.suggestion is not None:
        # One field serves both the step-redo suggestion and the tool-deny reason.
        payload["suggestion"] = body.suggestion
        payload["reason"] = body.suggestion
    try:
        runner.resolve_loop_gate_decision(run_id, action=action, payload=payload or None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return LoopGateDecisionResponse(action=action)


@router.post("/{run_id}/loop-gate-arm", response_model=LoopGateArmResponse)
async def loop_gate_arm(run_id: str, body: LoopGateArmRequest) -> LoopGateArmResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if ctx.status != "running":
        raise HTTPException(status_code=409, detail="Engagement is not currently running")

    kind = body.kind.strip().lower()
    if kind not in _GATE_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {_GATE_KINDS}")

    try:
        runner.arm_gate(run_id, body.committee, kind, armed=body.armed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return LoopGateArmResponse(committee=body.committee, kind=kind, armed=body.armed)
