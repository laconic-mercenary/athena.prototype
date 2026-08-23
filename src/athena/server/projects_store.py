"""Durable project scaffolding on disk.

A project is a directory under the projects root holding a project.json metadata file and a
private ensembles/ catalog. This module is the sole authority for creating, renaming,
deleting, and scanning projects, and keeps an in-memory index rebuilt from disk at startup.
The projects root is ATHENA_SRV_PROJECTS_DIR (default "workspace"); it is intentionally
separate from the engagement Registry — engagement-to-project wiring comes later.
"""

import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from athena import env_vars


###############
# CONSTS / GLOBALS #
###############

_log = logging.getLogger("athena.server.projects_store")

# Alphanumeric plus underscore, dash, dot — the name is also the on-disk directory name.
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_DEFAULT_ROOT = "workspace"
# The always-present project that engagements created without an explicit project land in.
DEFAULT_PROJECT_NAME = "default"
_METADATA_FILE = "project.json"
_ENSEMBLES_SUBDIR = "ensembles"
_ARTIFACTS_SUBDIR = "artifacts"
_META_KEY_NAME = "name"
_META_KEY_CREATED_AT = "created_at"

# name -> ProjectMeta, rebuilt from disk by load().
_projects: dict[str, "ProjectMeta"] = {}


###############
# CUSTOM TYPES #
###############

@dataclass(frozen=True)
class ProjectMeta:
    name: str
    created_at: float
    path: Path


###############
# FUNCTIONS #
###############

def projects_root() -> Path:
    return Path(os.environ.get(env_vars.SRV_PROJECTS_DIR, _DEFAULT_ROOT))


def engagement_artifacts_dir(project_name: str, run_id: str) -> Path:
    """Run-scoped artifacts directory for an engagement within a project. Not created here —
    the workflow mkdirs it on first write."""
    return projects_root() / project_name / _ARTIFACTS_SUBDIR / run_id


def private_ensemble_dir(project_name: str, ensemble_name: str) -> Path:
    """Path to a named ensemble in a project's private catalog. Existence is the caller's
    concern; the ensemble loader validates its manifest."""
    return projects_root() / project_name / _ENSEMBLES_SUBDIR / ensemble_name


def load() -> None:
    """Rebuild the in-memory index from disk. Called at server startup."""
    _projects.clear()
    root = projects_root()
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        meta = _read_meta(entry)
        if meta is not None:
            _projects[meta.name] = meta


def list_projects() -> list[ProjectMeta]:
    return sorted(_projects.values(), key=lambda p: p.name)


def get_project(name: str) -> "ProjectMeta | None":
    return _projects.get(name)


def ensure_project(name: str) -> ProjectMeta:
    """Return the project, creating it if it does not exist. Idempotent — used at startup to
    guarantee the default project is present."""
    existing = _projects.get(name)
    if existing is not None:
        return existing
    return create_project(name)


def create_project(name: str) -> ProjectMeta:
    _validate_name(name)
    if name in _projects:
        raise ValueError(f"Project already exists: {name!r}")
    path = projects_root() / name
    if path.exists():
        raise ValueError(f"Project directory already exists: {path}")
    (path / _ENSEMBLES_SUBDIR).mkdir(parents=True)
    created_at = time.time()
    _write_meta(path, name, created_at)
    meta = ProjectMeta(name=name, created_at=created_at, path=path)
    _projects[name] = meta
    return meta


def rename_project(old: str, new: str) -> ProjectMeta:
    _validate_name(new)
    meta = _projects.get(old)
    if meta is None:
        raise KeyError(f"No project: {old!r}")
    if new != old and new in _projects:
        raise ValueError(f"Project already exists: {new!r}")
    new_path = projects_root() / new
    if new_path != meta.path and new_path.exists():
        raise ValueError(f"Project directory already exists: {new_path}")
    meta.path.rename(new_path)
    _write_meta(new_path, new, meta.created_at)
    new_meta = ProjectMeta(name=new, created_at=meta.created_at, path=new_path)
    del _projects[old]
    _projects[new] = new_meta
    return new_meta


def delete_project(name: str) -> None:
    meta = _projects.pop(name, None)
    if meta is None:
        raise KeyError(f"No project: {name!r}")
    shutil.rmtree(meta.path)


###############
# NON PUBLIC FUNCTIONS #
###############

def _validate_name(name: str) -> None:
    if name in (".", "..") or not _NAME_RE.match(name or ""):
        raise ValueError(
            "Project name must be non-empty and contain only letters, digits, underscore, "
            "dash, or dot"
        )


def _read_meta(entry: Path) -> "ProjectMeta | None":
    if not entry.is_dir():
        return None
    meta_path = entry / _METADATA_FILE
    if not meta_path.is_file():
        return None
    try:
        raw = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("skipping project dir with unreadable metadata: %s (%s)", meta_path, exc)
        return None
    name = raw.get(_META_KEY_NAME)
    created_at = raw.get(_META_KEY_CREATED_AT)
    if not isinstance(name, str) or not isinstance(created_at, (int, float)):
        _log.warning("skipping project dir with malformed metadata: %s", meta_path)
        return None
    return ProjectMeta(name=name, created_at=float(created_at), path=entry)


def _write_meta(path: Path, name: str, created_at: float) -> None:
    (path / _METADATA_FILE).write_text(
        json.dumps({_META_KEY_NAME: name, _META_KEY_CREATED_AT: created_at})
    )
