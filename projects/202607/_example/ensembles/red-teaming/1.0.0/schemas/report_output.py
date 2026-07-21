from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class RiskRating(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ReportSection(BaseModel):
    title: str
    content: str


class ReportOutput(BaseModel):
    retrieval_output_id: str
    executive_summary: str
    risk_rating: RiskRating
    sections: list[ReportSection]
    recommendations: list[str]
