"""Tests for the code-first decision interface: PendingDecision subtypes and
Engagement.wait_for_decision().

Covers three layers:
- each PendingDecision subtype resolves through the right underlying Engagement
  method, and refuses a second resolution;
- build_loop_gate_decision dispatches on kind;
- wait_for_decision() itself: immediate return, blocking, terminal status, and
  multi-waiter behavior against the real gate handlers.
"""

from __future__ import annotations

import threading
import time

import pytest

from athena import engagement_status
from athena.server import runner
from athena.server.pending_decision import (
    CommitteeGateDecision,
    ElementGateDecision,
    OrchestratorQuestion,
    PlanApproval,
    StepGateDecision,
    ToolGateDecision,
    build_loop_gate_decision,
)


def _make_engagement(run_id: str = "run-1") -> runner.Engagement:
    return runner.Engagement(
        run_id=run_id,
        ensemble=object(),
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


# ---------------------------------------------------------------------------
# PendingDecision subtypes — each resolves through the real Engagement methods
# ---------------------------------------------------------------------------

def test_orchestrator_question_answer() -> None:
    eng = _make_engagement()
    OrchestratorQuestion(eng, "which domain?").answer("acme.example")
    assert eng.context.pending_answer == "acme.example"
    assert eng.context.reply_event.is_set()


def test_orchestrator_question_double_resolve_raises() -> None:
    decision = OrchestratorQuestion(_make_engagement(), "which domain?")
    decision.answer("acme.example")
    with pytest.raises(RuntimeError):
        decision.answer("other.example")


def test_orchestrator_question_does_not_set_await_phase() -> None:
    # chat.py's routing keys off pending_question vs. awaiting_approval specifically
    # because this phase leaves await_phase untouched — must not regress that.
    eng = _make_engagement()
    eng._set_pending_decision(OrchestratorQuestion(eng, "which domain?"))
    assert eng.context.await_phase == runner.AWAIT_NONE


def test_plan_approval_approve() -> None:
    eng = _make_engagement()
    decision = PlanApproval(eng, plan="the-plan")
    decision.approve()
    assert eng.context.plan_decision_type == "approve"
    assert eng.context.plan_decision_event.is_set()


def test_plan_approval_reject() -> None:
    eng = _make_engagement()
    PlanApproval(eng, plan="the-plan").reject()
    assert eng.context.plan_decision_type == "reject"


def test_plan_approval_request_revision() -> None:
    eng = _make_engagement()
    PlanApproval(eng, plan="the-plan").request_revision("go deeper")
    assert eng.context.plan_decision_type == "revise"
    assert eng.context.revision_message == "go deeper"


def test_plan_approval_double_resolve_raises() -> None:
    decision = PlanApproval(_make_engagement(), plan="the-plan")
    decision.approve()
    with pytest.raises(RuntimeError):
        decision.approve()
    with pytest.raises(RuntimeError):
        decision.reject()


def test_committee_gate_accept_and_redo() -> None:
    eng = _make_engagement()
    CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=True).accept()
    assert eng.context.gate_decision_action == "accept"

    eng2 = _make_engagement("run-2")
    CommitteeGateDecision(eng2, committee="recon", digest="d", redo_available=True).redo("try again")
    assert eng2.context.gate_decision_action == "redo"
    assert eng2.context.gate_decision_suggestion == "try again"


def test_committee_gate_double_resolve_raises() -> None:
    decision = CommitteeGateDecision(_make_engagement(), committee="recon", digest="d", redo_available=False)
    decision.accept()
    with pytest.raises(RuntimeError):
        decision.redo()


def test_element_gate_accept_override_redo() -> None:
    eng = _make_engagement()
    ElementGateDecision(
        eng, committee="recon", element_id="e1", winner_id="v1", rationale="r", variants=[],
    ).override("v2")
    assert eng.context.loop_gate_decision == {"action": "override", "winner_id": "v2"}


def test_step_gate_redo_carries_suggestion() -> None:
    eng = _make_engagement()
    StepGateDecision(eng, committee="recon", step_id="s1", description="d", digest="dig").redo("more depth")
    assert eng.context.loop_gate_decision == {"action": "redo", "suggestion": "more depth"}


def test_step_gate_skip() -> None:
    eng = _make_engagement()
    StepGateDecision(eng, committee="recon", step_id="s1", description="d", digest="dig").skip()
    assert eng.context.loop_gate_decision == {"action": "skip"}


def test_tool_gate_deny_carries_reason() -> None:
    eng = _make_engagement()
    ToolGateDecision(eng, committee="recon", tool="http_get", args={}, side_effect="touches_target").deny(
        "too noisy"
    )
    assert eng.context.loop_gate_decision == {"action": "deny", "reason": "too noisy"}


def test_tool_gate_approve() -> None:
    eng = _make_engagement()
    ToolGateDecision(eng, committee="recon", tool="http_get", args={}, side_effect="reads_local").approve()
    assert eng.context.loop_gate_decision == {"action": "approve"}


# ---------------------------------------------------------------------------
# build_loop_gate_decision
# ---------------------------------------------------------------------------

def test_build_loop_gate_decision_element() -> None:
    eng = _make_engagement()
    d = build_loop_gate_decision(
        eng, "element", "recon",
        {"element_id": "e1", "winner_id": "v1", "rationale": "r", "variants": [{"label": "v1"}]},
    )
    assert isinstance(d, ElementGateDecision)
    assert d.element_id == "e1"
    assert d.variants == [{"label": "v1"}]


def test_build_loop_gate_decision_step() -> None:
    eng = _make_engagement()
    d = build_loop_gate_decision(eng, "step", "recon", {"step_id": "s1", "description": "d", "digest": "x"})
    assert isinstance(d, StepGateDecision)
    assert d.step_id == "s1"


def test_build_loop_gate_decision_tool() -> None:
    eng = _make_engagement()
    d = build_loop_gate_decision(eng, "tool", "recon", {"tool": "http_get", "args": {}, "side_effect": "reads_local"})
    assert isinstance(d, ToolGateDecision)
    assert d.tool == "http_get"


def test_build_loop_gate_decision_unknown_kind_raises() -> None:
    with pytest.raises(ValueError):
        build_loop_gate_decision(_make_engagement(), "bogus", "recon", {})


# ---------------------------------------------------------------------------
# Engagement.wait_for_decision()
# ---------------------------------------------------------------------------

def test_wait_for_decision_returns_none_when_already_terminal() -> None:
    eng = _make_engagement()
    eng.context.status = engagement_status.COMPLETED
    assert eng.wait_for_decision(timeout=1) is None


def test_wait_for_decision_returns_immediately_if_already_pending() -> None:
    eng = _make_engagement()
    decision = CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=False)
    eng._set_pending_decision(decision)
    assert eng.wait_for_decision(timeout=1) is decision


def test_wait_for_decision_blocks_then_returns_new_decision() -> None:
    eng = _make_engagement()
    decision = CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=False)

    def publish_soon() -> None:
        time.sleep(0.05)
        eng._set_pending_decision(decision)

    threading.Thread(target=publish_soon, daemon=True).start()
    result = eng.wait_for_decision(timeout=2)
    assert result is decision


def test_wait_for_decision_times_out_with_nothing_pending() -> None:
    eng = _make_engagement()
    assert eng.wait_for_decision(timeout=0.05) is None


def test_wait_for_decision_wakes_on_abort_without_a_decision() -> None:
    eng = _make_engagement()
    eng.context.status = engagement_status.RUNNING

    def abort_soon() -> None:
        time.sleep(0.05)
        eng.abort()

    threading.Thread(target=abort_soon, daemon=True).start()
    assert eng.wait_for_decision(timeout=2) is None


def test_abort_clears_outstanding_decision_for_later_callers() -> None:
    eng = _make_engagement()
    eng.context.status = engagement_status.RUNNING
    decision = CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=False)
    eng._set_pending_decision(decision)

    eng.abort()

    # A caller that asks after the abort must see "nothing left to decide", not the
    # now-moot decision that was outstanding when the engagement was aborted.
    assert eng.wait_for_decision(timeout=0.05) is None


def test_multiple_waiters_see_the_same_decision() -> None:
    eng = _make_engagement()
    decision = CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=False)
    results: list = []

    def wait_and_record() -> None:
        results.append(eng.wait_for_decision(timeout=2))

    threads = [threading.Thread(target=wait_and_record) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    eng._set_pending_decision(decision)
    for t in threads:
        t.join(timeout=2)

    assert len(results) == 3
    assert all(r is decision for r in results)


def test_resolving_clears_pending_decision_for_next_waiter() -> None:
    eng = _make_engagement()
    decision = CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=False)
    eng._set_pending_decision(decision)
    decision.accept()
    # Immediately looping back must not see the same (now-resolved) decision again.
    assert eng.wait_for_decision(timeout=0.05) is None


def test_double_resolve_from_two_threads_only_one_wins() -> None:
    eng = _make_engagement()
    decision = CommitteeGateDecision(eng, committee="recon", digest="d", redo_available=False)
    errors: list[Exception] = []
    succeeded = []

    def try_accept() -> None:
        try:
            decision.accept()
            succeeded.append(True)
        except RuntimeError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=try_accept) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    assert len(succeeded) == 1
    assert len(errors) == 4


# ---------------------------------------------------------------------------
# Integration: the real gate handlers publish/clear pending decisions correctly
# ---------------------------------------------------------------------------

def test_gate_handler_publishes_committee_gate_decision_and_unblocks_on_accept() -> None:
    eng = _make_engagement()
    results: list = []

    def run_handler() -> None:
        results.append(eng._gate_handler("recon", "the digest", True))

    t = threading.Thread(target=run_handler, daemon=True)
    t.start()
    assert _wait_until(lambda: eng._pending_decision is not None)

    decision = eng.wait_for_decision(timeout=1)
    assert isinstance(decision, CommitteeGateDecision)
    assert decision.committee == "recon"
    assert decision.digest == "the digest"
    assert decision.redo_available is True

    decision.accept()
    t.join(timeout=2)
    assert results == [("accept", None)]
    assert eng._pending_decision is None
    assert eng.context.await_phase == runner.AWAIT_NONE


def test_ask_user_handler_publishes_orchestrator_question_and_unblocks_on_answer() -> None:
    eng = _make_engagement()
    results: list = []

    def run_handler() -> None:
        results.append(eng._ask_user_handler("which domain?"))

    t = threading.Thread(target=run_handler, daemon=True)
    t.start()
    assert _wait_until(lambda: eng._pending_decision is not None)

    decision = eng.wait_for_decision(timeout=1)
    assert isinstance(decision, OrchestratorQuestion)
    assert decision.question == "which domain?"
    assert eng.context.await_phase == runner.AWAIT_NONE  # unchanged — see chat.py routing

    decision.answer("acme.example")
    t.join(timeout=2)
    assert results == ["acme.example"]
    assert eng._pending_decision is None
    assert eng.context.pending_question is None


def test_loop_gate_handler_publishes_tool_gate_decision_and_unblocks_on_approve() -> None:
    eng = _make_engagement()
    results: list = []

    def run_handler() -> None:
        results.append(
            eng._loop_gate_handler("tool", "recon", {"tool": "http_get", "args": {"url": "x"}, "side_effect": "touches_target"})
        )

    t = threading.Thread(target=run_handler, daemon=True)
    t.start()
    assert _wait_until(lambda: eng._pending_decision is not None)

    decision = eng.wait_for_decision(timeout=1)
    assert isinstance(decision, ToolGateDecision)
    assert decision.tool == "http_get"
    assert decision.args == {"url": "x"}

    decision.approve()
    t.join(timeout=2)
    assert results == [{"action": "approve"}]
    assert eng._pending_decision is None
    assert eng.context.loop_gate_kind is None
