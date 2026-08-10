"""EngagementPlan — produced by the orchestrator during briefing.

The orchestrator submits this via submit_plan(); the harness validates it
and uses it to wire operator_approval gates and build per-committee briefs.
"""

from enum import Enum

from pydantic import BaseModel


###############
# CUSTOM TYPES #
###############

class GateType(str, Enum):
    """Enumeration of gate types the orchestrator may declare in an engagement plan.

    Currently only operator_approval is supported: the pipeline halts after the
    named committee until the operator explicitly approves via the plan-review gate.
    """

    operator_approval = "operator_approval"


class Gate(BaseModel):
    """A single operator-approval gate declared by the orchestrator.

    Specifies which committee the pipeline must pause after. The harness validates
    the 'after' field against the loaded ensemble's committee list at runtime.
    """

    after: str      # committee name — validated against the manifest at runtime
    type: GateType


class CommitteeBrief(BaseModel):
    """Per-committee instruction set produced by the orchestrator during briefing.

    Passed to the committee leader as part of its initial context. The objective
    list is ordered so the most recently appended entry carries the highest weight;
    the orchestrator may append refinements on retry or iterate decisions.
    """

    objective:   list[str]        # ordered; most recent has highest weight
    constraints: list[str] = []
    emphasis:    list[str] = []


class EngagementPlan(BaseModel):
    """The full engagement plan produced by the orchestrator at the end of briefing.

    Created when the orchestrator calls submit_plan() and immediately validated by the
    harness. Drives the entire engagement: per-committee briefs seed leader context,
    operator_instructions are surfaced to the operator for review, and gates pause the
    workflow at named checkpoints for explicit approval.
    """

    engagement_id:         str    # harness-assigned UUID
    operator_instructions: str
    committees:            dict[str, CommitteeBrief]
    gates:                 list[Gate] = []
