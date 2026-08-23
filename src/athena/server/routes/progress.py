"""GET /engagements/{run_id}/progress — coarse live progress for a projects-view row.

Lets a row render before it opens the SSE stream, and recover on reconnect (SSE has no
replay). Status and gate-awaiting are authoritative from the EngagementContext; the coarse
percent and current committee/specialist are derived from pipeline events by progress.py.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from athena import engagement_status
from athena.server import progress, runner


###############
# CONSTS / GLOBALS #
###############

router = APIRouter(prefix="/engagements")


###############
# CUSTOM TYPES #
###############

class Awaiting(BaseModel):
    kind: str            # an engagement_status.AWAIT_* phase token (plan | committee_gate | loop_gate)
    committee: str | None


class ProgressResponse(BaseModel):
    run_id: str
    status: str
    percent: int
    current_committee: str | None
    active_specialist: str | None
    awaiting: Awaiting | None


###############
# FUNCTIONS #
###############

@router.get("/{run_id}/progress", response_model=ProgressResponse)
async def get_progress(run_id: str) -> ProgressResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    derived = progress.snapshot(run_id)
    total = len(ctx.ensemble.committees) if ctx.ensemble else 0
    return ProgressResponse(
        run_id=run_id,
        status=ctx.status,
        percent=_percent(ctx.status, derived.completed_committees, total),
        current_committee=derived.current_committee,
        active_specialist=derived.active_specialist,
        awaiting=_awaiting(ctx),
    )


###############
# NON PUBLIC FUNCTIONS #
###############

def _percent(run_status: str, completed: int, total: int) -> int:
    if run_status == engagement_status.COMPLETED:
        return 100
    if total <= 0:
        return 0
    return min(100, round(100 * completed / total))


def _awaiting(ctx: runner.EngagementContext) -> Awaiting | None:
    phase = ctx.await_phase
    if phase == engagement_status.AWAIT_NONE:
        return None
    # The committee is known only for a committee gate; other phases aren't committee-scoped.
    committee = ctx.gate_committee if phase == engagement_status.AWAIT_COMMITTEE_GATE else None
    return Awaiting(kind=phase, committee=committee)
