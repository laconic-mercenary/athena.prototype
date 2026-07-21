from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class ActionPriority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class PlannedAction(BaseModel):
    id: str
    priority: ActionPriority
    title: str
    category: str
    description: str
    rationale: str
    observation_ids: list[str]


class PlanOutput(BaseModel):
    recon_output_id: str
    actions: list[PlannedAction]
    summary: str
