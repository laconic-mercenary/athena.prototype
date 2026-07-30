"""GET /engagements/{run_id}/artifacts          — list artifact files.
GET /engagements/{run_id}/artifacts/{name}    — serve artifact content.
POST /engagements/{run_id}/artifacts/{name}/reveal — reveal in OS file browser.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from athena.server import runner

router = APIRouter(prefix="/engagements")

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ARTIFACTS_ROOT = Path("artifacts")


class ArtifactMeta(BaseModel):
    name: str
    size: int


@router.get("/{run_id}/artifacts", response_model=list[ArtifactMeta])
async def list_artifacts(run_id: str) -> list[ArtifactMeta]:
    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    run_dir = _ARTIFACTS_ROOT / run_id
    if not run_dir.is_dir():
        return []
    return [
        ArtifactMeta(name=p.stem, size=p.stat().st_size)
        for p in sorted(run_dir.glob("*.json"))
    ]


@router.get("/{run_id}/artifacts/{name}", response_class=PlainTextResponse)
async def get_artifact(run_id: str, name: str) -> str:
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    path = _ARTIFACTS_ROOT / run_id / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return path.read_text()


@router.post("/{run_id}/artifacts/{name}/reveal", status_code=204)
async def reveal_artifact(run_id: str, name: str) -> None:
    """Open the artifact in the OS file browser (macOS: reveals in Finder)."""
    if not _SAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    if runner.get_context(run_id) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    path = (_ARTIFACTS_ROOT / run_id / f"{name}.json").resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        subprocess.Popen(["open", "-R", str(path)])
    except FileNotFoundError:
        raise HTTPException(status_code=501, detail="File browser not supported on this platform")
