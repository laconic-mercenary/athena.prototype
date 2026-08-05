"""Manifest summary + specialist enable/disable for the briefing tree."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from athena.server import runner

router = APIRouter(prefix="/engagements")

_MAX_KEY_LEN = 400


class SpecialistConfigRequest(BaseModel):
    # Compound key: "{committee}/{element_id}/{specialist_id}"
    key: str = Field(..., min_length=1, max_length=_MAX_KEY_LEN)
    enabled: bool


class SpecialistConfigResponse(BaseModel):
    key: str
    enabled: bool


@router.get("/{run_id}/manifest-summary")
async def manifest_summary(run_id: str) -> dict:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    try:
        return runner.get_manifest_summary(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/{run_id}/specialist-config", response_model=SpecialistConfigResponse)
async def specialist_config(
    run_id: str, body: SpecialistConfigRequest
) -> SpecialistConfigResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    try:
        runner.set_specialist_enabled(run_id, body.key, enabled=body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return SpecialistConfigResponse(key=body.key, enabled=body.enabled)
