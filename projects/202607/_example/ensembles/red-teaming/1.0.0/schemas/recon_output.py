from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class Classification(str, Enum):
    signal_critical = "signal_critical"
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


class Observation(BaseModel):
    id: str
    specialist_id: str
    command: str
    command_output: str
    classification: Classification
    category: Category
    comments: list[str]


class ThreatAnalysis(BaseModel):
    summary: str


class ReconOutput(BaseModel):
    target: str
    observations: list[Observation]
    summary: str
    threat_analysis: ThreatAnalysis | None = None
