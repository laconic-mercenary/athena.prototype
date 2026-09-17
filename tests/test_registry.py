"""Tests for the project/engagement registry and the Engagement construction seam.

Locks in the A1/A2 refactor: an Engagement owns its context and validates its inputs,
and the Registry tracks engagements by run_id across projects. The runner's module-level
get_context / is_busy delegate to that registry.
"""

import pytest

from athena import engagement_status
from athena.server import runner
from athena.server.registry import Registry


def _make_engagement(run_id: str = "run-1") -> runner.Engagement:
    # These tests never touch the ensemble, so a sentinel satisfies the constructor's
    # non-None check without loading a real one.
    return runner.Engagement(
        run_id=run_id,
        ensemble=object(),
        instructions="do the thing",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name="default",
    )


# ---------------------------------------------------------------------------
# Engagement construction seam
# ---------------------------------------------------------------------------

def test_engagement_initialises_context() -> None:
    sentinel = object()
    eng = runner.Engagement(
        run_id="run-x", ensemble=sentinel, instructions="go",
        orch_model="m", orch_provider="fake", orch_config={}, project_name="default",
    )
    ctx = eng.context
    assert eng.run_id == "run-x"
    assert ctx.run_id == "run-x"
    assert ctx.status == engagement_status.QUEUED
    assert ctx.await_phase == runner.AWAIT_NONE
    assert ctx.ensemble is sentinel
    assert ctx.leader_queues == {}
    assert ctx.armed_gates == {}
    assert ctx.awaiting_approval is False


def test_engagement_rejects_none_ensemble() -> None:
    with pytest.raises(ValueError):
        runner.Engagement(
            run_id="r", ensemble=None, instructions="go",
            orch_model="m", orch_provider="fake", orch_config={}, project_name="default",
        )


def test_engagement_rejects_non_dict_config() -> None:
    with pytest.raises(ValueError):
        runner.Engagement(
            run_id="r", ensemble=object(), instructions="go",
            orch_model="m", orch_provider="fake", orch_config="{}", project_name="default",
        )


@pytest.mark.parametrize("overrides", [
    {"run_id": "   "},
    {"instructions": ""},
    {"orch_model": ""},
    {"orch_provider": "  "},
    {"project_name": "  "},
])
def test_engagement_rejects_blank_strings(overrides: dict) -> None:
    kwargs = dict(
        run_id="r", ensemble=object(), instructions="go",
        orch_model="m", orch_provider="fake", orch_config={}, project_name="default",
    )
    kwargs.update(overrides)
    with pytest.raises(ValueError):
        runner.Engagement(**kwargs)


# ---------------------------------------------------------------------------
# Registry seam
# ---------------------------------------------------------------------------

def test_fresh_registry_is_idle_and_empty() -> None:
    reg = Registry()
    assert reg.is_busy() is False
    assert reg.get_engagement("nope") is None
    assert reg.get_context("nope") is None


def test_add_and_get_engagement() -> None:
    reg = Registry()
    eng = _make_engagement("run-1")
    reg.add_engagement(eng)
    assert reg.get_engagement("run-1") is eng
    assert reg.get_context("run-1") is eng.context


def test_remove_engagement() -> None:
    reg = Registry()
    eng = _make_engagement("run-1")
    reg.add_engagement(eng)
    reg.remove_engagement("run-1")
    assert reg.get_engagement("run-1") is None


def test_remove_unknown_engagement_is_noop() -> None:
    reg = Registry()
    reg.remove_engagement("ghost")
    assert reg.get_engagement("ghost") is None


def test_is_busy_tracks_running_status() -> None:
    reg = Registry()
    eng = _make_engagement("run-1")
    reg.add_engagement(eng)
    assert reg.is_busy() is False  # queued, not yet executing
    eng.context.status = engagement_status.RUNNING
    assert reg.is_busy() is True
    eng.context.status = engagement_status.COMPLETED
    assert reg.is_busy() is False


def test_engagements_for_project_filters_by_project() -> None:
    reg = Registry()
    a = runner.Engagement(
        run_id="a", ensemble=object(), instructions="x",
        orch_model="m", orch_provider="fake", orch_config={}, project_name="alpha",
    )
    b = runner.Engagement(
        run_id="b", ensemble=object(), instructions="x",
        orch_model="m", orch_provider="fake", orch_config={}, project_name="beta",
    )
    reg.add_engagement(a)
    reg.add_engagement(b)
    assert [e.run_id for e in reg.engagements_for_project("alpha")] == ["a"]
    assert [e.run_id for e in reg.engagements_for_project("beta")] == ["b"]
    assert reg.engagements_for_project("ghost") == []


def test_tracks_multiple_engagements_independently() -> None:
    reg = Registry()
    a = _make_engagement("run-a")
    b = _make_engagement("run-b")
    reg.add_engagement(a)
    reg.add_engagement(b)
    assert reg.get_engagement("run-a") is a
    assert reg.get_engagement("run-b") is b
    reg.remove_engagement("run-a")
    assert reg.get_engagement("run-a") is None
    assert reg.get_engagement("run-b") is b


# ---------------------------------------------------------------------------
# Runner delegation
# ---------------------------------------------------------------------------

def test_runner_get_context_and_is_busy_delegate(monkeypatch) -> None:
    reg = Registry()
    monkeypatch.setattr(runner, "_registry", reg)
    eng = _make_engagement("run-1")
    reg.add_engagement(eng)
    eng.context.status = engagement_status.RUNNING
    assert runner.get_context("run-1") is eng.context
    assert runner.is_busy() is True


def test_runner_get_engagement_delegates(monkeypatch) -> None:
    reg = Registry()
    monkeypatch.setattr(runner, "_registry", reg)
    eng = _make_engagement("run-1")
    reg.add_engagement(eng)
    assert runner.get_engagement("run-1") is eng
    assert runner.get_engagement("nope") is None


# ---------------------------------------------------------------------------
# Engagement action methods (moved off runner.py's free functions)
# ---------------------------------------------------------------------------

def test_engagement_resolve_gate_decision_sets_fields_and_event() -> None:
    eng = _make_engagement("run-1")
    eng.resolve_gate_decision(action="redo", suggestion="dig deeper")
    ctx = eng.context
    assert ctx.gate_decision_action == "redo"
    assert ctx.gate_decision_suggestion == "dig deeper"
    assert ctx.gate_decision_event.is_set()


def test_engagement_abort_marks_abandoned_and_wakes_all_events() -> None:
    eng = _make_engagement("run-1")
    eng.abort()
    ctx = eng.context
    assert ctx.cancelled is True
    assert ctx.status == engagement_status.ABANDONED
    assert ctx.reply_event.is_set()
    assert ctx.plan_decision_event.is_set()
    assert ctx.gate_decision_event.is_set()
    assert ctx.loop_gate_event.is_set()


def test_engagement_set_specialist_enabled_toggles_key() -> None:
    eng = _make_engagement("run-1")
    key = "recon/web_osint/analyst"
    eng.set_specialist_enabled(key, enabled=False)
    assert key in eng.context.disabled_specialists
    eng.set_specialist_enabled(key, enabled=True)
    assert key not in eng.context.disabled_specialists


def test_engagement_arm_gate_adds_and_removes_kind() -> None:
    eng = _make_engagement("run-1")
    eng.arm_gate("recon", "tool", armed=True)
    assert eng.context.armed_gates == {"recon": {"tool"}}
    eng.arm_gate("recon", "tool", armed=False)
    assert eng.context.armed_gates == {"recon": set()}


def test_runner_resolve_gate_decision_wrapper_delegates(monkeypatch) -> None:
    reg = Registry()
    monkeypatch.setattr(runner, "_registry", reg)
    eng = _make_engagement("run-1")
    reg.add_engagement(eng)
    runner.resolve_gate_decision("run-1", action="accept", suggestion=None)
    assert eng.context.gate_decision_action == "accept"


def test_runner_resolve_gate_decision_wrapper_raises_for_unknown_run(monkeypatch) -> None:
    reg = Registry()
    monkeypatch.setattr(runner, "_registry", reg)
    with pytest.raises(KeyError):
        runner.resolve_gate_decision("ghost", action="accept", suggestion=None)


def test_runner_abort_engagement_wrapper_is_noop_for_unknown_run(monkeypatch) -> None:
    reg = Registry()
    monkeypatch.setattr(runner, "_registry", reg)
    runner.abort_engagement("ghost")  # must not raise
