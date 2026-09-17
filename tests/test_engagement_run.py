"""Integration-level tests for Engagement.run()'s terminal-status handling.

The heavy dependencies (OrchestratorHarness, run_workflow) are stubbed — as
test_runner_concurrency.py's precedent already establishes for this method, nothing
in the unit suite exercises the real orchestrator/workflow machinery end-to-end (that's
covered by the Docker-based system tests). This file only pins the status Engagement.run()
leaves behind for each terminal outcome.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from athena import engagement_status
from athena.harness.committee_runner import RefuseStartError
from athena.server import runner


class _FakePlan:
    committees: dict = {}


class _FakeOrchestrator:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start_briefing(self, **kwargs) -> None:
        pass

    def run_briefing(self):
        return _FakePlan()

    def run_loop(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def inject_revision(self, message: str) -> None:
        pass


def _make_engagement(run_id: str = "run-1") -> runner.Engagement:
    return runner.Engagement(
        run_id=run_id,
        ensemble=SimpleNamespace(committees={}, name="e", version="1", capability="cap"),
        instructions="do the thing",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name="default",
    )


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _run_to_plan_gate_then(monkeypatch, run_workflow_stub, eng) -> threading.Thread:
    monkeypatch.setattr(runner, "OrchestratorHarness", _FakeOrchestrator)
    monkeypatch.setattr(runner, "make_backend", lambda *a, **kw: object())
    monkeypatch.setattr(runner, "run_workflow", run_workflow_stub)
    t = threading.Thread(target=eng.run, daemon=True)
    t.start()
    assert _wait_until(lambda: eng.context.await_phase == runner.AWAIT_PLAN)
    eng.resolve_approval(approved=True)
    return t


def test_refused_workflow_sets_rejected_not_completed(monkeypatch) -> None:
    """Regression test for audit finding H1: a committee refusal used to fall through
    to ctx.status = COMPLETED because run_workflow() swallowed RefuseStartError and
    returned normally. It now re-raises, and Engagement.run() maps that to REJECTED."""

    def fake_run_workflow(**kwargs):
        raise RefuseStartError("objective is impossible")

    eng = _make_engagement()
    t = _run_to_plan_gate_then(monkeypatch, fake_run_workflow, eng)
    t.join(timeout=2)

    assert eng.context.status == engagement_status.REJECTED
    assert eng._pending_decision is None


def test_normal_completion_sets_completed(monkeypatch) -> None:
    def fake_run_workflow(**kwargs):
        return None

    eng = _make_engagement()
    t = _run_to_plan_gate_then(monkeypatch, fake_run_workflow, eng)
    t.join(timeout=2)

    assert eng.context.status == engagement_status.COMPLETED


def test_unexpected_exception_sets_failed_not_rejected(monkeypatch) -> None:
    def fake_run_workflow(**kwargs):
        raise ValueError("boom")

    eng = _make_engagement()
    t = _run_to_plan_gate_then(monkeypatch, fake_run_workflow, eng)
    t.join(timeout=2)

    assert eng.context.status == engagement_status.FAILED


def test_seed_text_reaches_run_workflow(monkeypatch) -> None:
    """Engagement.run() must pass its own _seed_text through to run_workflow() —
    run_workflow()'s own entry-only gating is covered separately in test_workflow.py."""
    captured: dict = {}

    def fake_run_workflow(**kwargs):
        captured["seed_text"] = kwargs.get("seed_text")

    eng = runner.Engagement(
        run_id="run-seeded",
        ensemble=SimpleNamespace(committees={}, name="e", version="1", capability="cap"),
        instructions="do the thing",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name="default",
        seed_text="background from a prior engagement",
    )
    t = _run_to_plan_gate_then(monkeypatch, fake_run_workflow, eng)
    t.join(timeout=2)

    assert captured["seed_text"] == "background from a prior engagement"


def test_no_seed_text_by_default(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_workflow(**kwargs):
        captured["seed_text"] = kwargs.get("seed_text")

    eng = _make_engagement()
    t = _run_to_plan_gate_then(monkeypatch, fake_run_workflow, eng)
    t.join(timeout=2)

    assert captured["seed_text"] is None
