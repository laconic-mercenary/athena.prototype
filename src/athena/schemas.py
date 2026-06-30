"""Shared pydantic schemas for the Athena pipeline artifact chain."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

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
