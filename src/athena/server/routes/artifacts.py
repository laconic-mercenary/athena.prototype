"""GET /engagements/{run_id}/artifacts      — list artifact files.
GET /engagements/{run_id}/artifacts/{name} — serve artifact content.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from athena.server import runner

router = APIRouter(prefix="/engagements")

# Allowlist: artifact names are lowercase identifiers (e.g. recon, plan, report).
# Blocks path traversal and shell metacharacters at the boundary.
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ArtifactMeta(BaseModel):
    name: str   # bare name without extension, e.g. "recon"
    size: int


def _artifacts_dir(request: Request) -> Path:
    return request.app.state.config.artifacts_dir


@router.get("/{run_id}/artifacts", response_model=list[ArtifactMeta])
async def list_artifacts(run_id: str, request: Request) -> list[ArtifactMeta]:
    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

    run_dir = _artifacts_dir(request) / run_id
    if not run_dir.is_dir():
        return []

    results: list[ArtifactMeta] = []
    for path in sorted(run_dir.glob("*.json")):
        results.append(ArtifactMeta(name=path.stem, size=path.stat().st_size))
    return results


@router.get("/{run_id}/artifacts/{name}/markdown", response_class=PlainTextResponse)
async def get_artifact_markdown(run_id: str, name: str, request: Request) -> str:
    """Serve the rendered markdown report for an artifact (e.g. plan.md, report.md).

    Only some committees produce a .md rendering; retrieval/plan/report do, recon
    and approval do not. A missing .md is a 404, distinct from an unknown name (400).
    """
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid artifact name")

    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

    path = _artifacts_dir(request) / run_id / f"{name}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Markdown report not found")

    return path.read_text()


@router.get("/{run_id}/artifacts/{name}", response_class=PlainTextResponse)
async def get_artifact(run_id: str, name: str, request: Request) -> str:
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid artifact name")

    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

    path = _artifacts_dir(request) / run_id / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return path.read_text()
