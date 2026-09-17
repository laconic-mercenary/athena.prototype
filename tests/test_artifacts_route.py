"""Tests that the artifacts route reads from the engagement's project-scoped directory
(workspace/<project>/artifacts/<run_id>), the relocation introduced in B5.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from athena import env_vars
from athena.server import runner
from athena.server.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _engagement(run_id: str, project: str) -> runner.Engagement:
    return runner.Engagement(
        run_id=run_id,
        ensemble=SimpleNamespace(committees={}),
        instructions="x",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name=project,
    )


def test_artifacts_dir_is_project_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    eng = _engagement("run-art", "proj")
    assert eng.context.artifacts_dir == tmp_path / "proj" / "artifacts" / "run-art"


def test_artifacts_route_reads_from_project_scoped_dir(tmp_path, monkeypatch, client) -> None:
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    eng = _engagement("run-art", "proj")
    runner._registry.add_engagement(eng)
    try:
        eng.context.artifacts_dir.mkdir(parents=True)
        (eng.context.artifacts_dir / "recon.json").write_text('{"ok": true}')

        listing = client.get("/engagements/run-art/artifacts")
        assert listing.status_code == 200
        assert [a["name"] for a in listing.json()] == ["recon"]

        body = client.get("/engagements/run-art/artifacts/recon")
        assert body.status_code == 200
        assert body.text == '{"ok": true}'
    finally:
        runner._registry.remove_engagement("run-art")
