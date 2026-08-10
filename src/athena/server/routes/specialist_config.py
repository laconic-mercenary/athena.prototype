"""Manifest summary + specialist enable/disable for the briefing tree."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from athena.server import limits, runner

###############
# CONSTS / GLOBALS #
###############

router = APIRouter(prefix="/engagements")


###############
# CUSTOM TYPES #
###############

class SpecialistConfigRequest(BaseModel):
    # Compound key: "{committee}/{element_id}/{specialist_id}"
    key: str = Field(..., min_length=1, max_length=limits.MAX_KEY_LEN)
    enabled: bool


class SpecialistConfigResponse(BaseModel):
    key: str
    enabled: bool


###############
# FUNCTIONS #
###############

@router.get("/{run_id}/manifest-summary")
async def manifest_summary(run_id: str) -> dict:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    try:
        return runner.get_manifest_summary(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/{run_id}/specialist-config", response_model=SpecialistConfigResponse)
async def specialist_config(
    run_id: str, body: SpecialistConfigRequest
) -> SpecialistConfigResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    try:
        runner.set_specialist_enabled(run_id, body.key, enabled=body.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SpecialistConfigResponse(key=body.key, enabled=body.enabled)
