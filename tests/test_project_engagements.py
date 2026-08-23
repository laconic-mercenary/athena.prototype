"""Tests for the project-scoped engagement endpoints under /projects/{name}/engagements.

The create-and-run path starts a real pipeline thread, so these tests cover the routing,
validation, listing, and delete behavior — engagements are registered directly rather than
run — plus the 404 paths that stop before any pipeline starts.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from athena import env_vars
from athena.server import projects_store, runner
from athena.server.app import create_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    projects_store.load()
    yield tmp_path
    projects_store._projects.clear()


@pytest.fixture
def client(env):
    return TestClient(create_app())


def _register(run_id: str, project: str) -> runner.Engagement:
    eng = runner.Engagement(
        run_id=run_id,
        ensemble=SimpleNamespace(committees={}),
        instructions="x",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name=project,
    )
    runner._registry.add_engagement(eng)
    return eng


def test_list_engagements_scoped_to_project(client) -> None:
    projects_store.create_project("proj")
    _register("r1", "proj")
    _register("r2", "proj")
    _register("r3", "other")
    try:
        data = client.get("/projects/proj/engagements").json()
        assert {e["run_id"] for e in data["engagements"]} == {"r1", "r2"}
    finally:
        for r in ("r1", "r2", "r3"):
            runner._registry.remove_engagement(r)


def test_list_engagements_404_for_unknown_project(client) -> None:
    r = client.get("/projects/ghost/engagements")
    assert r.status_code == 404


def test_delete_engagement(client) -> None:
    projects_store.create_project("proj")
    _register("r1", "proj")
    try:
        r = client.delete("/projects/proj/engagements/r1")
        assert r.status_code == 204
        assert runner._registry.get_engagement("r1") is None
    finally:
        runner._registry.remove_engagement("r1")


def test_create_engagement_404_for_unknown_project(client) -> None:
    r = client.post("/projects/ghost/engagements", json={"instructions": "do it"})
    assert r.status_code == 404


def test_create_engagement_404_for_unknown_ensemble(client, monkeypatch) -> None:
    monkeypatch.setenv(env_vars.SRV_ORCHESTRATOR_MODEL, "m")
    monkeypatch.setenv(env_vars.SRV_ORCHESTRATOR_PROVIDER, "fake")
    monkeypatch.setenv(env_vars.SRV_ORCHESTRATOR_CONFIG, "{}")
    projects_store.create_project("proj")
    r = client.post(
        "/projects/proj/engagements",
        json={"instructions": "do it", "ensemble": "missing"},
    )
    assert r.status_code == 404
