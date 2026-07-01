"""Shared pydantic schemas for the Athena pipeline artifact chain."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from athena.utils import new_id, new_short_id


class Classification(str, Enum):
    signal_warn = "signal_warn"
    signal_info = "signal_info"
    noise = "noise"
    unknown = "unknown"


class Category(str, Enum):
    network = "network"
    service = "service"
    configuration = "configuration"
    exposure = "exposure"
    authentication = "authentication"


class Specialist(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str


class Comment(BaseModel):
    author_id: str
    text: str


class RawFinding(BaseModel):
    id: str = Field(default_factory=new_short_id)
    specialist_id: str
    command: str
    command_output: str
    notes: str


class Observation(BaseModel):
    id: str = Field(default_factory=new_short_id)
    specialist_id: str
    command: str
    command_output: str
    classification: Classification
    category: Category
    comments: list[Comment]


class ReconArtifact(BaseModel):
    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "recon"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    specialists: list[Specialist]
    observations: list[Observation]
    summary: str


class ActionPriority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class PlannedAction(BaseModel):
    id: str = Field(default_factory=new_short_id)
    priority: ActionPriority
    title: str
    category: str
    description: str
    rationale: str
    observation_ids: list[str] = Field(default_factory=list)


class PlanArtifact(BaseModel):
    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "planning"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    recon_artifact_id: str
    actions: list[PlannedAction]
    summary: str


class RetrievedFinding(BaseModel):
    id: str = Field(default_factory=new_short_id)
    specialist_id: str
    action_id: str  # references PlannedAction.id; empty string if cross-cutting
    tool: str
    tool_input: dict[str, Any]
    tool_output: str
    notes: str


class RetrievalArtifact(BaseModel):
    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "retrieval"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    plan_artifact_id: str
    findings: list[RetrievedFinding]
    summary: str


class RiskRating(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ReportSection(BaseModel):
    title: str
    content: str


class ReportArtifact(BaseModel):
    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "reporting"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    retrieval_artifact_id: str
    executive_summary: str
    risk_rating: RiskRating
    sections: list[ReportSection]
    recommendations: list[str]


class OrchestratorApproval(BaseModel):
    run_id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    notes: str


class OrchestratorRejection(BaseModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
