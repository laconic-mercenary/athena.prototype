"""Tests for workflow graph helper functions."""

from athena.ensemble.types import WorkflowNode, WorkflowTransition
from athena.harness.workflow import (
    _clear_downstream,
    _forward_target,
    _has_declared_transition,
    _is_terminal,
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
    from unittest.mock import MagicMock
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
