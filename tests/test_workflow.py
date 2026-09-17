"""Tests for workflow graph helper functions."""

from unittest.mock import MagicMock

from pydantic import BaseModel

from athena.ensemble.types import WorkflowNode, WorkflowTransition
from athena.harness import workflow as workflow_mod
from athena.harness.orchestrator import GateDecision
from athena.harness.workflow import (
    _clear_downstream,
    _forward_target,
    _has_declared_transition,
    _is_terminal,
    find_terminal_committee,
    run_workflow,
)


def _node(*transitions: tuple[str, str | None]) -> WorkflowNode:
    """Build a WorkflowNode with the given (to, condition) transitions."""
    from pydantic import BaseModel
    class _Schema(BaseModel):
        pass
    return WorkflowNode(
        name="test",
        transitions=[WorkflowTransition(to=to, condition=cond) for to, cond in transitions],
        output_schema=_Schema,
    )


# ---------------------------------------------------------------------------
# _is_terminal
# ---------------------------------------------------------------------------

def test_is_terminal_no_transitions():
    node = _node()
    assert _is_terminal(node) is True


def test_is_terminal_only_retry():
    node = _node(("a", "retry"))
    assert _is_terminal(node) is True


def test_is_terminal_only_iterate():
    node = _node(("a", "iterate"))
    assert _is_terminal(node) is True


def test_is_terminal_with_forward():
    node = _node(("a", None))
    assert _is_terminal(node) is False


def test_is_terminal_with_forward_and_retry():
    node = _node(("a", None), ("a", "retry"))
    assert _is_terminal(node) is False


# ---------------------------------------------------------------------------
# _forward_target
# ---------------------------------------------------------------------------

def test_forward_target_none_when_no_unconditional():
    node = _node(("a", "retry"))
    assert _forward_target(node) is None


def test_forward_target_returns_unconditional():
    node = _node(("b", None))
    assert _forward_target(node) == "b"


def test_forward_target_ignores_conditional():
    node = _node(("a", "retry"), ("b", None))
    assert _forward_target(node) == "b"


# ---------------------------------------------------------------------------
# _has_declared_transition
# ---------------------------------------------------------------------------

def test_has_declared_transition_found():
    node = _node(("a", "retry"))
    assert _has_declared_transition(node, "retry", "a") is True


def test_has_declared_transition_wrong_condition():
    node = _node(("a", "retry"))
    assert _has_declared_transition(node, "iterate", "a") is False


def test_has_declared_transition_wrong_target():
    node = _node(("a", "retry"))
    assert _has_declared_transition(node, "retry", "b") is False


def test_has_declared_transition_forward():
    node = _node(("b", None))
    assert _has_declared_transition(node, None, "b") is True


# ---------------------------------------------------------------------------
# _clear_downstream
# ---------------------------------------------------------------------------

def _make_ensemble(chain: list[str]):
    """Build a minimal LoadedEnsemble whose workflow is a linear chain."""
    from pydantic import BaseModel

    class _Schema(BaseModel):
        pass

    workflow = {}
    for i, name in enumerate(chain):
        if i + 1 < len(chain):
            transitions = [WorkflowTransition(to=chain[i + 1], condition=None)]
        else:
            transitions = []
        workflow[name] = WorkflowNode(name=name, transitions=transitions, output_schema=_Schema)

    ensemble = MagicMock()
    ensemble.workflow = workflow
    ensemble.entry = chain[0] if chain else None
    return ensemble


def test_clear_downstream_clears_intermediate():
    ensemble = _make_ensemble(["a", "b", "c", "d"])
    artifacts = {"a": "x", "b": "y", "c": "z", "d": "w"}
    retry_counts: dict = {}
    iterate_counts: dict = {}
    # back-edge fires: retry "a", so clear b and c (between a and d, exclusive d)
    _clear_downstream("a", "d", ensemble, artifacts, retry_counts, iterate_counts)
    assert "a" in artifacts  # from_committee excluded
    assert "b" not in artifacts
    assert "c" not in artifacts
    assert "d" in artifacts  # to_committee excluded


def test_clear_downstream_noop_when_adjacent():
    ensemble = _make_ensemble(["a", "b"])
    artifacts = {"a": "x", "b": "y"}
    retry_counts: dict = {}
    iterate_counts: dict = {}
    _clear_downstream("a", "b", ensemble, artifacts, retry_counts, iterate_counts)
    # nothing between a and b
    assert "a" in artifacts
    assert "b" in artifacts


# ---------------------------------------------------------------------------
# find_terminal_committee
# ---------------------------------------------------------------------------

def test_find_terminal_committee_walks_to_the_end():
    ensemble = _make_ensemble(["a", "b", "c"])
    assert find_terminal_committee(ensemble) == "c"


def test_find_terminal_committee_single_node():
    ensemble = _make_ensemble(["a"])
    assert find_terminal_committee(ensemble) == "a"


def test_find_terminal_committee_none_on_cycle():
    # a -> b -> a, no node ever lacks a forward edge, so no terminal is reachable.
    ensemble = MagicMock()
    ensemble.entry = "a"
    ensemble.workflow = {
        "a": WorkflowNode(name="a", transitions=[WorkflowTransition(to="b", condition=None)], output_schema=None),
        "b": WorkflowNode(name="b", transitions=[WorkflowTransition(to="a", condition=None)], output_schema=None),
    }
    assert find_terminal_committee(ensemble) is None


def test_find_terminal_committee_ignores_retry_iterate_edges():
    ensemble = MagicMock()
    ensemble.entry = "a"
    ensemble.workflow = {
        "a": WorkflowNode(
            name="a",
            transitions=[
                WorkflowTransition(to="a", condition="retry"),
                WorkflowTransition(to="a", condition="iterate"),
            ],
            output_schema=None,
        ),
    }
    assert find_terminal_committee(ensemble) == "a"


# ---------------------------------------------------------------------------
# run_workflow — seed_text is only injected on the entry committee
# ---------------------------------------------------------------------------

def test_run_workflow_seeds_entry_committee_only(monkeypatch, tmp_path) -> None:
    class _Artifact(BaseModel):
        pass

    calls: list[dict] = []

    def fake_run_committee_with_ensemble(**kwargs):
        calls.append({"committee_name": kwargs["committee_name"], "seed_text": kwargs.get("seed_text")})
        return _Artifact(), False

    monkeypatch.setattr(workflow_mod, "run_committee_with_ensemble", fake_run_committee_with_ensemble)

    ensemble = MagicMock()
    ensemble.entry = "a"
    ensemble.workflow = {
        "a": WorkflowNode(name="a", transitions=[WorkflowTransition(to="b", condition=None)], output_schema=_Artifact),
        "b": WorkflowNode(name="b", transitions=[], output_schema=_Artifact),
    }
    ensemble.committees = {"a": MagicMock(), "b": MagicMock()}

    plan = MagicMock()
    plan.committees = {}
    plan.gates = []

    orchestrator = MagicMock()
    orchestrator.run_gate.return_value = GateDecision(decision="advance", rationale="ok")

    run_workflow(
        ensemble=ensemble,
        plan=plan,
        orchestrator=orchestrator,
        make_backend=lambda *a, **kw: object(),
        artifacts_dir=tmp_path,
        run_id="run-seed-test",
        ask_operator_handler=lambda q: "",
        gate_handler=lambda *a, **kw: ("accept", None),
        leader_queues={},
        global_step_budget=100,
        seed_text="SEEDED CONTENT",
    )

    assert [c["committee_name"] for c in calls] == ["a", "b"]
    assert calls[0]["seed_text"] == "SEEDED CONTENT"
    assert calls[1]["seed_text"] is None


def test_run_workflow_no_seed_text_by_default(monkeypatch, tmp_path) -> None:
    class _Artifact(BaseModel):
        pass

    calls: list[dict] = []

    def fake_run_committee_with_ensemble(**kwargs):
        calls.append({"seed_text": kwargs.get("seed_text")})
        return _Artifact(), False

    monkeypatch.setattr(workflow_mod, "run_committee_with_ensemble", fake_run_committee_with_ensemble)

    ensemble = MagicMock()
    ensemble.entry = "a"
    ensemble.workflow = {"a": WorkflowNode(name="a", transitions=[], output_schema=_Artifact)}
    ensemble.committees = {"a": MagicMock()}

    plan = MagicMock()
    plan.committees = {}
    plan.gates = []

    orchestrator = MagicMock()
    orchestrator.run_gate.return_value = GateDecision(decision="advance", rationale="ok")

    run_workflow(
        ensemble=ensemble,
        plan=plan,
        orchestrator=orchestrator,
        make_backend=lambda *a, **kw: object(),
        artifacts_dir=tmp_path,
        run_id="run-no-seed-test",
        ask_operator_handler=lambda q: "",
        gate_handler=lambda *a, **kw: ("accept", None),
        leader_queues={},
        global_step_budget=100,
    )

    assert calls == [{"seed_text": None}]
