"""Shared pydantic schemas for the Athena pipeline artifact chain."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from athena.utils import new_id, new_short_id


###############
# CUSTOM TYPES #
###############

class Classification(str, Enum):
    """Signal strength classification applied to a recon observation.

    The recon leader assigns this when promoting a RawFinding to an Observation.
    signal_critical and signal_warn findings drive the highest-priority planned actions.
    """

    signal_critical = "signal_critical"
    signal_warn = "signal_warn"
    signal_info = "signal_info"
    noise = "noise"
    unknown = "unknown"


class Category(str, Enum):
    """Domain category for a recon observation, used to group findings in the report."""

    network = "network"
    service = "service"
    configuration = "configuration"
    exposure = "exposure"
    authentication = "authentication"


class Specialist(BaseModel):
    """A record of one specialist agent that participated in the recon committee run.

    Stored in ReconArtifact.specialists so downstream committees and the report
    can attribute observations to the agent that produced them.
    """

    id: str = Field(default_factory=new_id)
    title: str


class Comment(BaseModel):
    """An inline annotation on an Observation, authored by a specialist or leader.

    Stored in Observation.comments so the planning committee can see how the
    recon leader or peers assessed a finding before acting on it.
    """

    author_id: str
    text: str


class RawFinding(BaseModel):
    """An unclassified specialist finding: the raw command invocation and output.

    Specialists emit RawFindings during recon; the committee leader reviews them
    and promotes significant ones to Observations with explicit classification and
    category, discarding noise.
    """

    id: str = Field(default_factory=new_short_id)
    specialist_id: str
    command: str
    command_output: str
    notes: str


class Observation(BaseModel):
    """A classified and categorized recon finding, promoted from a RawFinding.

    The recon leader creates Observations by evaluating RawFindings and assigning
    a Classification and Category. Only Observations (not RawFindings) appear in
    the final ReconArtifact and feed into the planning committee.
    """

    id: str = Field(default_factory=new_short_id)
    specialist_id: str
    command: str
    command_output: str
    classification: Classification
    category: Category
    comments: list[Comment]


class ThreatAnalysis(BaseModel):
    """High-level threat narrative synthesized by the recon leader.

    Produced alongside the observation list as the recon committee's final judgment:
    a prose summary of what the target's posture implies for the engagement.
    """

    summary: str


class ReconArtifact(BaseModel):
    """The recon committee's complete output artifact.

    Written to disk as JSON at the end of the recon run and passed as context to
    the planning committee. Contains the full observation list, the participating
    specialist roster, and the leader's threat analysis summary.
    """

    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "recon"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    specialists: list[Specialist]
    observations: list[Observation]
    summary: str
    threat_analysis: ThreatAnalysis | None = None


class ActionPriority(str, Enum):
    """Priority level assigned to a planned action by the planning committee leader."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class PlannedAction(BaseModel):
    """One discrete action item produced by the planning committee.

    Each action references the recon observations that motivated it and carries
    a priority so the retrieval committee can sequence its work. observation_ids
    links back to Observation.id entries in the ReconArtifact.
    """

    id: str = Field(default_factory=new_short_id)
    priority: ActionPriority
    title: str
    category: str
    description: str
    rationale: str
    observation_ids: list[str] = Field(default_factory=list)


class PlanArtifact(BaseModel):
    """The planning committee's complete output artifact.

    Produced after the planning leader synthesizes the ReconArtifact into an
    ordered list of PlannedActions. Passed to the retrieval committee as its
    primary input; recon_artifact_id provides the provenance chain.
    """

    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "planning"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    recon_artifact_id: str
    actions: list[PlannedAction]
    summary: str


class RetrievedFinding(BaseModel):
    """One exploitation or evidence-retrieval result from a retrieval specialist.

    Ties a specialist's actual tool call and output back to the PlannedAction it
    was executing. action_id is empty for cross-cutting findings not tied to a
    specific planned action.
    """

    id: str = Field(default_factory=new_short_id)
    specialist_id: str
    action_id: str  # references PlannedAction.id; empty string if cross-cutting
    tool: str
    tool_input: dict[str, Any]
    tool_output: str
    notes: str


class RetrievalArtifact(BaseModel):
    """The retrieval committee's complete output artifact.

    Produced after retrieval specialists execute against the target. Contains all
    RetrievedFindings from the run and is the primary input to the reporting committee.
    plan_artifact_id provides the provenance chain back to the planned actions.
    """

    artifact_id: str = Field(default_factory=new_id)
    run_id: str
    committee: str = "retrieval"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    plan_artifact_id: str
    findings: list[RetrievedFinding]
    summary: str


class RiskRating(str, Enum):
    """Overall risk rating applied to the engagement by the reporting committee."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ReportSection(BaseModel):
    """One titled section of the final report produced by the reporting committee."""

    title: str
    content: str


class ReportArtifact(BaseModel):
    """The reporting committee's final output — the deliverable for the engagement.

    Synthesizes the full artifact chain (recon → planning → retrieval) into a
    structured report with an executive summary, risk rating, narrative sections,
    and prioritized recommendations. retrieval_artifact_id anchors the chain.
    """

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
    """Legacy orchestrator approval record from the pre-ensemble pipeline.

    Kept for backward compatibility with older artifact files. The current
    pipeline uses EngagementPlan and GateDecision instead.
    """

    run_id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target: str
    notes: str


class OrchestratorRejection(BaseModel):
    """Legacy orchestrator rejection record from the pre-ensemble pipeline.

    Kept for backward compatibility with older artifact files. The current
    pipeline surfaces rejections as engagement status REJECTED with operator rationale.
    """

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
