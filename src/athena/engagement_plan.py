"""EngagementPlan — produced by the orchestrator during briefing.

The orchestrator submits this via submit_plan(); the harness validates it
and uses it to wire operator_approval gates and build per-committee briefs.
"""

from enum import Enum

from pydantic import BaseModel


class GateType(str, Enum):
    operator_approval = "operator_approval"


class Gate(BaseModel):
    after: str      # committee name — validated against the manifest at runtime
    type: GateType


class CommitteeBrief(BaseModel):
    objective:   list[str]        # ordered; most recent has highest weight
    constraints: list[str] = []
    emphasis:    list[str] = []


class EngagementPlan(BaseModel):
    engagement_id:         str    # harness-assigned UUID
    operator_instructions: str
    committees:            dict[str, CommitteeBrief]
    gates:                 list[Gate] = []
