"""Durable project scaffolding on disk.

A project is a directory under the projects root holding a project.json metadata file and a
private ensembles/ catalog. `ProjectStore` is the sole authority for creating, renaming,
deleting, and scanning projects, and keeps an in-memory index rebuilt from disk at startup.
The projects root is ATHENA_SRV_PROJECTS_DIR (default "workspace"); it is intentionally
separate from the engagement Registry — Project.engagements bridges the two on demand.
"""

import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from athena import engagement_status, env_vars

if TYPE_CHECKING:
    from athena.server.runner import Engagement


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


###############
# CUSTOM TYPES #
###############

class Project:
    """One project: durable metadata plus behavior.

    Owned by a ProjectStore, which is the only thing that mutates the store's index —
    rename()/delete() below are convenience methods that delegate back to it, so the
    index-mutation logic (re-keying the dict, checking for collisions) lives in one place.
    """

    def __init__(self, name: str, created_at: float, path: Path, *, store: "ProjectStore") -> None:
        self.name = name
        self.created_at = created_at
        self.path = path
        self._store = store

    def __repr__(self) -> str:
        return f"Project(name={self.name!r}, created_at={self.created_at})"

    def private_ensemble_dir(self, ensemble_name: str) -> Path:
        """Path to a named ensemble in this project's private catalog. Existence is the
        caller's concern; the ensemble loader validates its manifest."""
        return self.path / _ENSEMBLES_SUBDIR / ensemble_name

    def artifacts_dir(self, run_id: str) -> Path:
        """Run-scoped artifacts directory for an engagement within this project. Not
        created here — the workflow mkdirs it on first write."""
        return self.path / _ARTIFACTS_SUBDIR / run_id

    @property
    def engagements(self) -> list["Engagement"]:
        """Live engagements currently tracked against this project.

        Local import: runner.py imports this module for path resolution at engagement
        construction time, so this module cannot import runner at module scope without
        creating a cycle. Deferred here since nothing calls this before runner exists.
        """
        from athena.server import runner
        return runner.engagements_for_project(self.name)

    def start_engagement(self, instructions: str, ensemble_name: str | None = None) -> "Engagement":
        """Start a new engagement in this project. See runner.start_engagement()."""
        from athena.server import runner
        return runner.start_engagement(instructions, self.name, ensemble_name)

    def rename(self, new_name: str) -> None:
        self._store.rename(self.name, new_name)

    def delete(self) -> None:
        self._store.delete(self.name)


class ProjectStore:
    """In-memory index of Projects, mirrored to disk under projects_root(). Analogous to
    Registry for engagements: this is the one place that creates, renames, deletes, and
    scans projects."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}

    def load(self) -> None:
        """Rebuild the in-memory index from disk. Called at server startup."""
        self._projects.clear()
        root = projects_root()
        if not root.is_dir():
            return
        for entry in sorted(root.iterdir()):
            project = self._read_meta(entry)
            if project is not None:
                self._projects[project.name] = project

    def list(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.name)

    def get(self, name: str) -> Project | None:
        return self._projects.get(name)

    def ensure(self, name: str) -> Project:
        """Return the project, creating it if it does not exist. Idempotent — used at
        startup to guarantee the default project is present."""
        existing = self._projects.get(name)
        if existing is not None:
            return existing
        return self.create(name)

    def create(self, name: str) -> Project:
        _validate_name(name)
        if name in self._projects:
            raise ValueError(f"Project already exists: {name!r}")
        path = projects_root() / name
        if path.exists():
            raise ValueError(f"Project directory already exists: {path}")
        (path / _ENSEMBLES_SUBDIR).mkdir(parents=True)
        created_at = time.time()
        _write_meta(path, name, created_at)
        project = Project(name=name, created_at=created_at, path=path, store=self)
        self._projects[name] = project
        return project

    def rename(self, old: str, new: str) -> Project:
        _validate_name(new)
        project = self._projects.get(old)
        if project is None:
            raise KeyError(f"No project: {old!r}")
        if new != old and new in self._projects:
            raise ValueError(f"Project already exists: {new!r}")
        new_path = projects_root() / new
        if new_path != project.path and new_path.exists():
            raise ValueError(f"Project directory already exists: {new_path}")
        project.path.rename(new_path)
        _write_meta(new_path, new, project.created_at)
        # Mutate in place (rather than replacing with a new Project) so a reference the
        # caller already holds stays valid and up to date after the rename.
        del self._projects[old]
        project.name = new
        project.path = new_path
        self._projects[new] = project
        return project

    def delete(self, name: str) -> None:
        """Delete a project directory.

        Refuses if any of its engagements are still live (queued or running) — deleting
        out from under a running engagement would rmtree the directory it's actively
        writing artifacts into, and orphan the Engagement the registry still tracks. The
        operator must stop those first.
        """
        project = self._projects.get(name)
        if project is None:
            raise KeyError(f"No project: {name!r}")
        live = [e for e in project.engagements if e.context.status not in engagement_status.TERMINAL]
        if live:
            raise ValueError(
                f"Project {name!r} has {len(live)} live engagement(s) — abort them before deleting"
            )
        del self._projects[name]
        shutil.rmtree(project.path)

    def _read_meta(self, entry: Path) -> "Project | None":
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
        return Project(name=name, created_at=float(created_at), path=entry, store=self)


###############
# FUNCTIONS #
###############

def projects_root() -> Path:
    return Path(os.environ.get(env_vars.SRV_PROJECTS_DIR, _DEFAULT_ROOT))


###############
# NON PUBLIC FUNCTIONS #
###############

def _validate_name(name: str) -> None:
    if name in (".", "..") or not _NAME_RE.match(name or ""):
        raise ValueError(
            "Project name must be non-empty and contain only letters, digits, underscore, "
            "dash, or dot"
        )


def _write_meta(path: Path, name: str, created_at: float) -> None:
    (path / _METADATA_FILE).write_text(
        json.dumps({_META_KEY_NAME: name, _META_KEY_CREATED_AT: created_at})
    )


# ---------------------------------------------------------------------------
# Module-level singleton + thin wrappers (backward-compatible free-function API).
# Mirrors the runner.py / Registry split: one store instance, module functions delegate.
# ---------------------------------------------------------------------------

_store = ProjectStore()


def load() -> None:
    _store.load()


def list_projects() -> list[Project]:
    return _store.list()


def get_project(name: str) -> "Project | None":
    return _store.get(name)


def ensure_project(name: str) -> Project:
    return _store.ensure(name)


def create_project(name: str) -> Project:
    return _store.create(name)


def rename_project(old: str, new: str) -> Project:
    return _store.rename(old, new)


def delete_project(name: str) -> None:
    _store.delete(name)


def engagement_artifacts_dir(project_name: str, run_id: str) -> Path:
    """Run-scoped artifacts directory for an engagement within a project. Falls back to
    plain path arithmetic when the project isn't in the store's index (e.g. a bare
    Engagement constructed directly in a test, never registered as a Project) — matches
    today's behavior of not requiring the project to "exist" for this to resolve."""
    project = _store.get(project_name)
    if project is not None:
        return project.artifacts_dir(run_id)
    return projects_root() / project_name / _ARTIFACTS_SUBDIR / run_id


def private_ensemble_dir(project_name: str, ensemble_name: str) -> Path:
    project = _store.get(project_name)
    if project is not None:
        return project.private_ensemble_dir(ensemble_name)
    return projects_root() / project_name / _ENSEMBLES_SUBDIR / ensemble_name
