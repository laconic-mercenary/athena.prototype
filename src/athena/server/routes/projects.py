"""Project CRUD.

POST   /projects            — create a project (scaffolds its directory + private ensembles/).
GET    /projects            — list projects.
PATCH  /projects/{name}     — rename a project.
DELETE /projects/{name}     — delete a project (the UI confirms before calling).
"""

import asyncio

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from athena.server import limits, projects_store, runner


###############
# CONSTS / GLOBALS #
###############

router = APIRouter(prefix="/projects")

_NOT_FOUND_DETAIL = "Project not found"


###############
# CUSTOM TYPES #
###############

class ProjectNameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ProjectResponse(BaseModel):
    name: str
    created_at: float


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class StartEngagementRequest(BaseModel):
    instructions: str = Field(..., min_length=1, max_length=limits.MAX_INSTRUCTIONS_LEN)
    ensemble: str | None = Field(None, max_length=100)


class EngagementResponse(BaseModel):
    run_id: str
    status: str


class EngagementListResponse(BaseModel):
    engagements: list[EngagementResponse]


###############
# FUNCTIONS #
###############

@router.get("", response_model=ProjectListResponse)
async def list_projects() -> ProjectListResponse:
    return ProjectListResponse(
        projects=[ProjectResponse(name=p.name, created_at=p.created_at) for p in projects_store.list_projects()]
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectNameRequest) -> ProjectResponse:
    loop = asyncio.get_running_loop()
    try:
        meta = await loop.run_in_executor(None, projects_store.create_project, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ProjectResponse(name=meta.name, created_at=meta.created_at)


@router.patch("/{name}", response_model=ProjectResponse)
async def rename_project(name: str, body: ProjectNameRequest) -> ProjectResponse:
    loop = asyncio.get_running_loop()
    try:
        meta = await loop.run_in_executor(None, projects_store.rename_project, name, body.name)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ProjectResponse(name=meta.name, created_at=meta.created_at)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(name: str) -> None:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, projects_store.delete_project, name)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)


@router.post("/{name}/engagements", response_model=EngagementResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_engagement(name: str, body: StartEngagementRequest) -> EngagementResponse:
    if projects_store.get_project(name) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    try:
        run_id = runner.start_engagement(body.instructions, name, body.ensemble)
    except runner.EnsembleNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    ctx = runner.get_context(run_id)
    return EngagementResponse(run_id=run_id, status=ctx.status if ctx else "unknown")


@router.get("/{name}/engagements", response_model=EngagementListResponse)
async def list_engagements(name: str) -> EngagementListResponse:
    if projects_store.get_project(name) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return EngagementListResponse(
        engagements=[
            EngagementResponse(run_id=e.run_id, status=e.context.status)
            for e in runner.engagements_for_project(name)
        ]
    )


@router.delete("/{name}/engagements/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_engagement(name: str, run_id: str) -> None:
    runner.delete_engagement(run_id)
