"""Tests for the derived progress snapshot (progress.py) and the progress route."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pubsub import pub

from athena import engagement_status, topics
from athena.server import progress, runner
from athena.server.app import create_app


def _make_engagement(run_id: str, committees: dict) -> runner.Engagement:
    return runner.Engagement(
        run_id=run_id,
        ensemble=SimpleNamespace(committees=committees),
        instructions="x",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name="default",
    )


@pytest.fixture
def client():
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Derived snapshot (progress.py)
# ---------------------------------------------------------------------------

def test_snapshot_tracks_committee_and_specialist_events() -> None:
    rid = "run-sub"
    assert progress.snapshot(rid) == progress.Snapshot(None, None, 0)
    pub.sendMessage(topics.COMMITTEE_STARTED, run_id=rid, committee="recon")
    pub.sendMessage(topics.AGENT_SPAWNED, run_id=rid, committee="recon", agent_id="a", title="Recon Bot", role="specialist")
    pub.sendMessage(topics.COMMITTEE_COMPLETED, run_id=rid, committee="recon")

    snap = progress.snapshot(rid)
    assert snap.current_committee == "recon"
    assert snap.active_specialist == "Recon Bot"
    assert snap.completed_committees == 1

    # A redo re-completes the same committee; distinct-count must not double-count it.
    pub.sendMessage(topics.COMMITTEE_COMPLETED, run_id=rid, committee="recon")
    assert progress.snapshot(rid).completed_committees == 1


# ---------------------------------------------------------------------------
# Progress route
# ---------------------------------------------------------------------------

def test_progress_route_404_for_unknown(client) -> None:
    r = client.get("/engagements/ghost/progress")
    assert r.status_code == 404


def test_progress_route_reports_percent_and_fields(client) -> None:
    rid = "run-prog"
    eng = _make_engagement(rid, {"a": 1, "b": 1, "c": 1, "d": 1})
    eng.context.status = engagement_status.RUNNING
    runner._registry.add_engagement(eng)
    try:
        pub.sendMessage(topics.COMMITTEE_STARTED, run_id=rid, committee="b")
        pub.sendMessage(topics.COMMITTEE_COMPLETED, run_id=rid, committee="a")
        pub.sendMessage(topics.AGENT_SPAWNED, run_id=rid, committee="b", agent_id="x", title="Planner", role="leader")
        data = client.get(f"/engagements/{rid}/progress").json()
        assert data["status"] == "running"
        assert data["percent"] == 25  # 1 of 4 committees complete
        assert data["current_committee"] == "b"
        assert data["active_specialist"] == "Planner"
        assert data["awaiting"] is None
    finally:
        runner._registry.remove_engagement(rid)


def test_progress_route_reports_awaiting_committee_gate(client) -> None:
    rid = "run-await"
    eng = _make_engagement(rid, {"a": 1})
    eng.context.status = engagement_status.RUNNING
    eng.context.await_phase = engagement_status.AWAIT_COMMITTEE_GATE
    eng.context.gate_committee = "a"
    runner._registry.add_engagement(eng)
    try:
        data = client.get(f"/engagements/{rid}/progress").json()
        assert data["awaiting"] == {"kind": engagement_status.AWAIT_COMMITTEE_GATE, "committee": "a"}
    finally:
        runner._registry.remove_engagement(rid)


def test_progress_route_percent_100_when_completed(client) -> None:
    rid = "run-done"
    eng = _make_engagement(rid, {"a": 1, "b": 1})
    eng.context.status = engagement_status.COMPLETED
    runner._registry.add_engagement(eng)
    try:
        data = client.get(f"/engagements/{rid}/progress").json()
        assert data["percent"] == 100
    finally:
        runner._registry.remove_engagement(rid)
