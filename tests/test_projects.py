"""Tests for the disk-backed project store and the project CRUD routes."""

import json

import pytest
from fastapi.testclient import TestClient

from athena import env_vars
from athena.server import projects_store
from athena.server.app import create_app


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    projects_store.load()
    yield tmp_path
    projects_store._projects.clear()


@pytest.fixture
def client(store):
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Store (disk)
# ---------------------------------------------------------------------------

def test_create_scaffolds_directory_and_metadata(store) -> None:
    meta = projects_store.create_project("alpha")
    proj_dir = store / "alpha"
    assert (proj_dir / "project.json").is_file()
    assert (proj_dir / "ensembles").is_dir()
    saved = json.loads((proj_dir / "project.json").read_text())
    assert saved["name"] == "alpha"
    assert saved["created_at"] == meta.created_at


def test_create_rejects_duplicate(store) -> None:
    projects_store.create_project("alpha")
    with pytest.raises(ValueError):
        projects_store.create_project("alpha")


@pytest.mark.parametrize("bad", ["", "has space", "a/b", "..", ".", "no$dollar"])
def test_create_rejects_invalid_names(store, bad) -> None:
    with pytest.raises(ValueError):
        projects_store.create_project(bad)


def test_rename_moves_directory_and_updates_metadata(store) -> None:
    projects_store.create_project("alpha")
    projects_store.rename_project("alpha", "beta")
    assert not (store / "alpha").exists()
    assert (store / "beta" / "project.json").is_file()
    assert json.loads((store / "beta" / "project.json").read_text())["name"] == "beta"
    assert projects_store.get_project("alpha") is None
    assert projects_store.get_project("beta") is not None


def test_delete_removes_directory(store) -> None:
    projects_store.create_project("alpha")
    projects_store.delete_project("alpha")
    assert not (store / "alpha").exists()
    assert projects_store.get_project("alpha") is None


def test_load_rebuilds_index_from_disk_and_ignores_non_projects(store) -> None:
    projects_store.create_project("alpha")
    projects_store.create_project("beta")
    # A stray file and a dir without project.json must be ignored by the scan.
    (store / "README.md").write_text("not a project")
    (store / "stray").mkdir()
    projects_store._projects.clear()
    projects_store.load()
    assert {p.name for p in projects_store.list_projects()} == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def test_create_list_route_roundtrip(client) -> None:
    r = client.post("/projects", json={"name": "alpha"})
    assert r.status_code == 201
    assert r.json()["name"] == "alpha"

    listing = client.get("/projects").json()["projects"]
    assert [p["name"] for p in listing] == ["alpha"]


def test_create_route_rejects_invalid_name(client) -> None:
    r = client.post("/projects", json={"name": "bad name"})
    assert r.status_code == 400


def test_create_route_rejects_duplicate(client) -> None:
    client.post("/projects", json={"name": "alpha"})
    r = client.post("/projects", json={"name": "alpha"})
    assert r.status_code == 400


def test_rename_route(client) -> None:
    client.post("/projects", json={"name": "alpha"})
    r = client.patch("/projects/alpha", json={"name": "beta"})
    assert r.status_code == 200
    assert r.json()["name"] == "beta"
    assert [p["name"] for p in client.get("/projects").json()["projects"]] == ["beta"]


def test_rename_route_404_for_unknown(client) -> None:
    r = client.patch("/projects/ghost", json={"name": "beta"})
    assert r.status_code == 404


def test_delete_route(client) -> None:
    client.post("/projects", json={"name": "alpha"})
    r = client.delete("/projects/alpha")
    assert r.status_code == 204
    assert client.get("/projects").json()["projects"] == []


def test_delete_route_404_for_unknown(client) -> None:
    r = client.delete("/projects/ghost")
    assert r.status_code == 404
