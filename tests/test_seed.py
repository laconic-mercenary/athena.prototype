"""Tests for runner._resolve_seed_text / SeedSpec / SeedNotFound.

Uses the fsscanv1 fixture ensemble (deprecated as a design example for new ensembles,
per generate-ensemble's guidance — but still a real, loadable ensemble, which is all
that's needed here: a genuine LoadedEnsemble + schema with render_full() to validate
the rendering pipeline against, mirroring the env/registration pattern already
established in test_project_engagements.py.
"""

import json
from pathlib import Path

import pytest

from athena import engagement_status, env_vars
from athena.ensemble.loader import load_ensemble
from athena.server import runner

_FIXTURE_ENSEMBLE = Path(__file__).parent / "ensembles" / "fsscanv1"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    yield tmp_path
    runner._registry._engagements.clear()


def _register_source(
    run_id: str,
    project: str,
    *,
    status: str = engagement_status.COMPLETED,
) -> runner.Engagement:
    ensemble = load_ensemble(_FIXTURE_ENSEMBLE)
    eng = runner.Engagement(
        run_id=run_id,
        ensemble=ensemble,
        instructions="scan it",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name=project,
    )
    eng.context.status = status
    eng.context.artifacts_dir.mkdir(parents=True, exist_ok=True)
    runner._registry.add_engagement(eng)
    return eng


def _write_report_artifact(artifacts_dir: Path, *, total_files: int = 3) -> None:
    report = {
        "directory": "/data",
        "summary": "three files found",
        "table_markdown": "| ext | count |\n|---|---|\n| .py | 3 |",
        "total_files": total_files,
    }
    (artifacts_dir / "report.json").write_text(json.dumps(report))


def _write_scan_artifact(artifacts_dir: Path) -> None:
    scan = {
        "directory": "/data",
        "counts": [{"extension": ".py", "count": 3}],
        "total_files": 3,
        "hidden_files": 0,
        "regular_files": 3,
        "skipped": [],
    }
    (artifacts_dir / "scan.json").write_text(json.dumps(scan))


def test_resolve_seed_text_happy_path_terminal_default(env) -> None:
    eng = _register_source("src-1", "proj-a")
    _write_report_artifact(eng.context.artifacts_dir)

    text = runner._resolve_seed_text(runner.SeedSpec(project="proj-a", run_id="src-1"))

    assert "Inventory" in text
    assert "three files found" in text
    assert "Total: 3" in text


def test_resolve_seed_text_explicit_committee_override(env) -> None:
    eng = _register_source("src-2", "proj-a")
    _write_scan_artifact(eng.context.artifacts_dir)
    _write_report_artifact(eng.context.artifacts_dir)

    # Override to the non-terminal committee — still resolves, since committee
    # renderability (not terminal-ness) is the only requirement for an override.
    text = runner._resolve_seed_text(runner.SeedSpec(project="proj-a", run_id="src-2", committee="scan"))
    assert isinstance(text, str)


def test_resolve_seed_text_unknown_run_id(env) -> None:
    with pytest.raises(runner.SeedNotFound, match="not found"):
        runner._resolve_seed_text(runner.SeedSpec(project="proj-a", run_id="does-not-exist"))


def test_resolve_seed_text_wrong_project(env) -> None:
    _register_source("src-3", "proj-a")
    with pytest.raises(runner.SeedNotFound, match="does not belong to project"):
        runner._resolve_seed_text(runner.SeedSpec(project="proj-b", run_id="src-3"))


def test_resolve_seed_text_not_completed(env) -> None:
    _register_source("src-4", "proj-a", status=engagement_status.RUNNING)
    with pytest.raises(runner.SeedNotFound, match="not completed"):
        runner._resolve_seed_text(runner.SeedSpec(project="proj-a", run_id="src-4"))


def test_resolve_seed_text_missing_artifact(env) -> None:
    _register_source("src-5", "proj-a")
    # No artifact written at all.
    with pytest.raises(runner.SeedNotFound, match="No artifact"):
        runner._resolve_seed_text(runner.SeedSpec(project="proj-a", run_id="src-5"))


def test_resolve_seed_text_unknown_committee_override(env) -> None:
    eng = _register_source("src-6", "proj-a")
    _write_report_artifact(eng.context.artifacts_dir)
    with pytest.raises(runner.SeedNotFound, match="No artifact"):
        runner._resolve_seed_text(
            runner.SeedSpec(project="proj-a", run_id="src-6", committee="does_not_exist")
        )
