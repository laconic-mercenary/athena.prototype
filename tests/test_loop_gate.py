"""Tests for the in-loop operator gate family (element gate first).

Covers three layers:
- `_apply_element_gate` — the pure decision helper (accept / override / redo / not-armed).
- the threading rendezvous — the helper really blocks until the operator resolves.
- the runner channel + route guards, including the H3 phase-enum regression (a
  wrong-phase POST is now rejected instead of silently no-oping).
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from athena import engagement_status
from athena.ensemble.types import LoadedSkill, LoadedSpecialist
from athena.harness.committee_runner import (
    LoopGateHooks,
    _apply_element_gate,
    _apply_step_gate,
    _apply_tool_gate,
    _run_one_specialist,
)
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.server import runner
from athena.server.app import create_app

_VARIANTS = [{"label": "Variant 1", "title": "cautious"}, {"label": "Variant 2", "title": "bold"}]
_VALID = {"v1", "v2"}


def _hooks(*, armed: bool, decision: dict | None = None) -> LoopGateHooks:
    calls: list[dict] = []

    def is_armed(kind: str, committee: str) -> bool:
        return armed

    def decide(kind: str, committee: str, payload: dict) -> dict:
        calls.append({"kind": kind, "committee": committee, "payload": payload})
        return decision or {"action": "accept"}

    h = LoopGateHooks(is_armed=is_armed, decide=decide)
    h.calls = calls  # type: ignore[attr-defined]  # test introspection
    return h


# ---------------------------------------------------------------------------
# Pure decision helper
# ---------------------------------------------------------------------------

def test_not_armed_passes_through_without_consulting_operator() -> None:
    h = _hooks(armed=False)
    winner, reprompt, note = _apply_element_gate(
        h, "report", element_id="e", winner_id="v1", rationale="r",
        variants=_VARIANTS, valid_ids=_VALID,
    )
    assert (winner, reprompt, note) == ("v1", None, None)
    assert h.calls == []  # decide() must not be called when disarmed


def test_hooks_none_is_a_noop() -> None:
    assert _apply_element_gate(
        None, "report", element_id="e", winner_id="v1", rationale="r",
        variants=_VARIANTS, valid_ids=_VALID,
    ) == ("v1", None, None)


def test_accept_keeps_the_leaders_winner() -> None:
    h = _hooks(armed=True, decision={"action": "accept"})
    winner, reprompt, note = _apply_element_gate(
        h, "report", element_id="e", winner_id="v1", rationale="r",
        variants=_VARIANTS, valid_ids=_VALID,
    )
    assert (winner, reprompt, note) == ("v1", None, None)
    assert h.calls[0]["payload"]["winner_id"] == "v1"


def test_override_swaps_to_a_valid_winner() -> None:
    h = _hooks(armed=True, decision={"action": "override", "winner_id": "v2"})
    winner, reprompt, note = _apply_element_gate(
        h, "report", element_id="e", winner_id="v1", rationale="r",
        variants=_VARIANTS, valid_ids=_VALID,
    )
    assert winner == "v2"
    assert reprompt is None
    assert note is not None and "v2" in note


def test_override_to_unknown_winner_fails_safe_to_leader_choice() -> None:
    h = _hooks(armed=True, decision={"action": "override", "winner_id": "ghost"})
    winner, reprompt, note = _apply_element_gate(
        h, "report", element_id="e", winner_id="v1", rationale="r",
        variants=_VARIANTS, valid_ids=_VALID,
    )
    assert (winner, reprompt, note) == ("v1", None, None)  # keeps the valid original


def test_redo_returns_a_reselect_instruction() -> None:
    h = _hooks(armed=True, decision={"action": "redo"})
    winner, reprompt, note = _apply_element_gate(
        h, "report", element_id="e", winner_id="v1", rationale="r",
        variants=_VARIANTS, valid_ids=_VALID,
    )
    assert winner == "v1"
    assert reprompt is not None and "select_result" in reprompt
    assert note is None


# ---------------------------------------------------------------------------
# Tool-call authorization gate (Step 2)
# ---------------------------------------------------------------------------

def test_tool_gate_not_armed_approves_without_consulting() -> None:
    h = _hooks(armed=False)
    assert _apply_tool_gate(h, "exploit", tool="scan", args={}, side_effect="touches_target") == (True, None)
    assert h.calls == []


def test_tool_gate_approve_runs_the_tool() -> None:
    h = _hooks(armed=True, decision={"action": "approve"})
    approved, reason = _apply_tool_gate(h, "exploit", tool="scan", args={"host": "x"}, side_effect="touches_target")
    assert approved is True and reason is None
    assert h.calls[0]["payload"] == {"tool": "scan", "args": {"host": "x"}, "side_effect": "touches_target"}


def test_tool_gate_deny_blocks_with_reason() -> None:
    h = _hooks(armed=True, decision={"action": "deny", "reason": "too noisy"})
    approved, reason = _apply_tool_gate(h, "exploit", tool="scan", args={}, side_effect="touches_target")
    assert approved is False
    assert reason == "too noisy"


def test_tool_gate_deny_defaults_reason_when_blank() -> None:
    h = _hooks(armed=True, decision={"action": "deny"})
    approved, reason = _apply_tool_gate(h, "exploit", tool="scan", args={}, side_effect="touches_target")
    assert approved is False and reason  # non-empty fallback


# ---------------------------------------------------------------------------
# Post-step quality gate (Step 3)
# ---------------------------------------------------------------------------

def test_step_gate_not_armed_accepts() -> None:
    h = _hooks(armed=False)
    assert _apply_step_gate(h, "scan", step_id="s1", description="d", digest="out") == ("accept", None)
    assert h.calls == []


def test_step_gate_accept() -> None:
    h = _hooks(armed=True, decision={"action": "accept"})
    assert _apply_step_gate(h, "scan", step_id="s1", description="d", digest="out") == ("accept", None)


def test_step_gate_redo_carries_suggestion() -> None:
    h = _hooks(armed=True, decision={"action": "redo", "suggestion": "recount hidden files"})
    outcome, note = _apply_step_gate(h, "scan", step_id="s1", description="d", digest="out")
    assert outcome == "redo"
    assert note == "recount hidden files"


def test_step_gate_skip() -> None:
    h = _hooks(armed=True, decision={"action": "skip"})
    assert _apply_step_gate(h, "scan", step_id="s1", description="d", digest="out") == ("skip", None)


# ---------------------------------------------------------------------------
# Threading rendezvous — the gate really blocks until resolved
# ---------------------------------------------------------------------------

def test_element_gate_blocks_until_operator_resolves() -> None:
    release = threading.Event()
    slot: dict = {}

    def is_armed(kind: str, committee: str) -> bool:
        return True

    def decide(kind: str, committee: str, payload: dict) -> dict:
        release.wait(timeout=2)
        return slot["decision"]

    hooks = LoopGateHooks(is_armed=is_armed, decide=decide)
    out: dict = {}

    def worker() -> None:
        out["result"] = _apply_element_gate(
            hooks, "report", element_id="e", winner_id="v1", rationale="r",
            variants=_VARIANTS, valid_ids=_VALID,
        )

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    assert "result" not in out  # still blocked on the operator

    slot["decision"] = {"action": "override", "winner_id": "v2"}
    release.set()
    t.join(timeout=2)
    assert out["result"][0] == "v2"


def test_lock_guarded_decide_serializes_concurrent_tool_gates() -> None:
    # Compare-mode runs specialists in parallel, so several tool-call gates can fire at
    # once. The runner guards its handler with a lock (`with loop_gate_lock:`) so the
    # operator decides them one at a time. This proves that discipline: with a
    # lock-guarded decide(), no two gate decisions occupy the critical section together.
    lock = threading.Lock()
    in_section = [0]
    max_concurrent = [0]

    def guarded_decide(kind: str, committee: str, payload: dict) -> dict:
        with lock:
            in_section[0] += 1
            max_concurrent[0] = max(max_concurrent[0], in_section[0])
            time.sleep(0.02)
            in_section[0] -= 1
            return {"action": "approve"}

    hooks = LoopGateHooks(is_armed=lambda k, c: True, decide=guarded_decide)
    results: list = []

    def worker() -> None:
        results.append(_apply_tool_gate(hooks, "exploit", tool="t", args={}, side_effect="touches_target"))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    assert max_concurrent[0] == 1  # never two gate decisions at once
    assert results == [(True, None)] * 4


# ---------------------------------------------------------------------------
# Runner channel functions + await-phase property
# ---------------------------------------------------------------------------

def _make_engagement(run_id: str) -> runner.Engagement:
    # The gate-channel and route-guard tests never touch the ensemble, so a sentinel
    # object satisfies the constructor's non-None check without loading a real one.
    return runner.Engagement(
        run_id=run_id,
        ensemble=object(),
        instructions="test",
        orch_model="m",
        orch_provider="fake",
        orch_config={},
        project_name="default",
    )


@pytest.fixture
def ctx():
    eng = _make_engagement("run-test")
    runner._registry.add_engagement(eng)
    yield eng.context
    runner._registry.remove_engagement("run-test")


def test_awaiting_approval_property_tracks_phase(ctx) -> None:
    ctx.await_phase = runner.AWAIT_NONE
    assert ctx.awaiting_approval is False
    for phase in (runner.AWAIT_PLAN, runner.AWAIT_COMMITTEE_GATE, runner.AWAIT_LOOP_GATE):
        ctx.await_phase = phase
        assert ctx.awaiting_approval is True


def test_arm_gate_toggles_armed_kinds(ctx) -> None:
    runner.arm_gate("run-test", "report", "element", armed=True)
    assert ctx.armed_gates["report"] == {"element"}
    runner.arm_gate("run-test", "report", "tool", armed=True)
    assert ctx.armed_gates["report"] == {"element", "tool"}
    runner.arm_gate("run-test", "report", "element", armed=False)
    assert ctx.armed_gates["report"] == {"tool"}


def test_resolve_loop_gate_sets_decision_and_event(ctx) -> None:
    assert not ctx.loop_gate_event.is_set()
    runner.resolve_loop_gate_decision("run-test", action="override", payload={"winner_id": "v2"})
    assert ctx.loop_gate_decision == {"action": "override", "winner_id": "v2"}
    assert ctx.loop_gate_event.is_set()


def test_resolve_loop_gate_unknown_run_raises() -> None:
    with pytest.raises(KeyError):
        runner.resolve_loop_gate_decision("nope", action="accept")


# ---------------------------------------------------------------------------
# Integration: the tool gate wired through a real specialist run (H11 / P2)
# ---------------------------------------------------------------------------

def _skill(executed: list) -> LoadedSkill:
    def impl(**kwargs):
        executed.append(kwargs)
        return {"ok": True}
    return LoadedSkill(
        id="count", name="count_files", description="count", impl=impl,
        parameters={"type": "object", "properties": {"directory": {"type": "string"}}},
    )


def _specialist_with(skill: LoadedSkill) -> LoadedSpecialist:
    return LoadedSpecialist(
        id="s1", title="S1", system="sys", model="m", provider="fake",
        temperature=None, skill_ids=[skill.id], max_tokens=None,
    )


def _call(name: str, tc_id: str = "tc1", **inp) -> ModelResponse:
    return ModelResponse(stop_reason="tool_use", text=None, tool_calls=[ToolCall(id=tc_id, name=name, input=inp)])


def _run_spec(skill, backend, hooks):
    return _run_one_specialist(
        _specialist_with(skill), "task", {skill.id: skill},
        "scan", "run1", lambda p, u=None, *_: backend, "run1.scan.e",
        loop_gate_hooks=hooks,
    )


def test_tool_gate_wiring_approve_executes_skill() -> None:
    executed: list = []
    skill = _skill(executed)
    backend = FakeBackend([_call("count_files", directory="/x"), ModelResponse(stop_reason="end_turn", text="done")])
    hooks = LoopGateHooks(is_armed=lambda k, c: True, decide=lambda k, c, p: {"action": "approve"})
    out = _run_spec(skill, backend, hooks)
    assert out == "done"
    assert executed == [{"directory": "/x"}]  # the skill actually ran


def test_tool_gate_wiring_deny_blocks_skill_and_reaches_model() -> None:
    executed: list = []
    skill = _skill(executed)
    backend = FakeBackend([_call("count_files", directory="/x"), ModelResponse(stop_reason="end_turn", text="done")])
    hooks = LoopGateHooks(is_armed=lambda k, c: True, decide=lambda k, c, p: {"action": "deny", "reason": "too noisy"})
    out = _run_spec(skill, backend, hooks)
    assert out == "done"
    assert executed == []                                   # skill NOT executed
    tool_result = backend.recorded[0][1][0]                 # (response, results)[0] first result
    assert "denied" in tool_result and "too noisy" in tool_result


def test_tool_gate_deny_does_not_consume_executed_budget() -> None:
    # H14: a denial must not burn SPECIALIST_MAX_TOOL_CALLS — the specialist can propose
    # a different action, and the second (approved) call executes.
    executed: list = []
    skill = _skill(executed)
    backend = FakeBackend([
        _call("count_files", tc_id="t1", directory="/a"),
        _call("count_files", tc_id="t2", directory="/b"),
        ModelResponse(stop_reason="end_turn", text="done"),
    ])
    decisions = iter([{"action": "deny", "reason": "no"}, {"action": "approve"}])
    hooks = LoopGateHooks(is_armed=lambda k, c: True, decide=lambda k, c, p: next(decisions))
    out = _run_spec(skill, backend, hooks)
    assert out == "done"
    assert executed == [{"directory": "/b"}]  # 1st denied (not run), 2nd approved (run)


def test_tool_gate_total_attempts_are_bounded() -> None:
    # After SPECIALIST_MAX_TOOL_ATTEMPTS denials the gate stops being consulted and the
    # specialist is told to finalize — bounding operator prompts per specialist.
    from athena.harness.committee_runner import SPECIALIST_MAX_TOOL_ATTEMPTS
    executed: list = []
    skill = _skill(executed)
    calls = [_call("count_files", tc_id=f"t{i}", directory=f"/{i}") for i in range(SPECIALIST_MAX_TOOL_ATTEMPTS + 1)]
    backend = FakeBackend([*calls, ModelResponse(stop_reason="end_turn", text="done")])
    consults = [0]

    def decide(k, c, p):
        consults[0] += 1
        return {"action": "deny"}

    hooks = LoopGateHooks(is_armed=lambda k, c: True, decide=decide)
    out = _run_spec(skill, backend, hooks)
    assert out == "done"
    assert executed == []                                   # never executed
    assert consults[0] == SPECIALIST_MAX_TOOL_ATTEMPTS       # gate not consulted past the cap
    last_result = backend.recorded[SPECIALIST_MAX_TOOL_ATTEMPTS][1][0]
    assert "Too many denied attempts" in last_result


def test_tool_gate_disarmed_runs_without_consulting() -> None:
    executed: list = []
    skill = _skill(executed)
    backend = FakeBackend([_call("count_files", directory="/x"), ModelResponse(stop_reason="end_turn", text="done")])
    consulted = [0]
    hooks = LoopGateHooks(is_armed=lambda k, c: False, decide=lambda k, c, p: (consulted.__setitem__(0, 1) or {"action": "approve"}))
    out = _run_spec(skill, backend, hooks)
    assert out == "done"
    assert executed == [{"directory": "/x"}]
    assert consulted[0] == 0  # disarmed → decide never called


# ---------------------------------------------------------------------------
# Route guards (incl. H3 phase-enum regression)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def route_ctx():
    eng = _make_engagement("run-route")
    eng.context.status = engagement_status.RUNNING
    runner._registry.add_engagement(eng)
    yield eng.context
    runner._registry.remove_engagement("run-route")


def test_loop_gate_decision_404_for_unknown_engagement(client) -> None:
    r = client.post("/engagements/ghost/loop-gate-decision", json={"action": "accept"})
    assert r.status_code == 404


def test_loop_gate_decision_409_when_not_in_loop_phase(client, route_ctx) -> None:
    route_ctx.await_phase = runner.AWAIT_NONE
    r = client.post("/engagements/run-route/loop-gate-decision", json={"action": "accept"})
    assert r.status_code == 409


def test_loop_gate_decision_releases_when_in_phase(client, route_ctx) -> None:
    route_ctx.await_phase = runner.AWAIT_LOOP_GATE
    r = client.post(
        "/engagements/run-route/loop-gate-decision",
        json={"action": "override", "winner_id": "v2"},
    )
    assert r.status_code == 200
    assert route_ctx.loop_gate_decision == {"action": "override", "winner_id": "v2"}
    assert route_ctx.loop_gate_event.is_set()


def test_loop_gate_arm_rejects_unknown_kind(client, route_ctx) -> None:
    r = client.post(
        "/engagements/run-route/loop-gate-arm",
        json={"committee": "report", "kind": "bogus", "armed": True},
    )
    assert r.status_code == 400


def test_loop_gate_arm_arms_the_context(client, route_ctx) -> None:
    r = client.post(
        "/engagements/run-route/loop-gate-arm",
        json={"committee": "report", "kind": "element", "armed": True},
    )
    assert r.status_code == 200
    assert "element" in route_ctx.armed_gates["report"]


def test_h3_gate_decision_rejected_during_plan_phase(client, route_ctx) -> None:
    # A stale committee-gate POST while briefing is awaiting plan approval must 409,
    # not fall through to the wrong channel.
    route_ctx.await_phase = runner.AWAIT_PLAN
    r = client.post("/engagements/run-route/gate-decision", json={"action": "accept"})
    assert r.status_code == 409


def test_h3_plan_review_rejected_during_committee_gate(client, route_ctx) -> None:
    # The headline H3 case: clicking Reject on a stale briefing tab while a committee
    # gate is active previously returned a false 200. It must now 409.
    route_ctx.await_phase = runner.AWAIT_COMMITTEE_GATE
    r = client.post("/engagements/run-route/plan-review", json={"action": "reject"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# SSE terminal-state replay on (re)connect — the "UI stuck after gate" fix
# ---------------------------------------------------------------------------

def test_events_replays_completed_status_on_connect(client, route_ctx) -> None:
    # A client that reconnects after the run finished must be told immediately, not hang
    # on heartbeats (SSE has no replay). This is what un-freezes a UI that dropped its
    # stream mid-run.
    route_ctx.status = "completed"
    r = client.get("/engagements/run-route/events")
    assert r.status_code == 200
    assert "engagement.completed" in r.text


def test_events_replays_failed_run_as_rejected(client, route_ctx) -> None:
    route_ctx.status = "failed"
    r = client.get("/engagements/run-route/events")
    assert "engagement.rejected" in r.text


def test_events_404_for_unknown_run(client) -> None:
    r = client.get("/engagements/ghost/events")
    assert r.status_code == 404
