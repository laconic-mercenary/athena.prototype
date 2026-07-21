from __future__ import annotations
from pydantic import BaseModel


class RetrievedFinding(BaseModel):
    id: str
    specialist_id: str
    action_id: str       # references PlannedAction.id; empty string if cross-cutting
    tool: str
    tool_input: dict
    tool_output: str
    notes: str


class RetrievalOutput(BaseModel):
    plan_output_id: str
    findings: list[RetrievedFinding]
    summary: str
