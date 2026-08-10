"""Tests for athena.engagement_status constants."""

from athena import engagement_status


# ---------------------------------------------------------------------------
# Engagement run status
# ---------------------------------------------------------------------------

def test_status_constants_are_non_empty_strings() -> None:
    for name in ("RUNNING", "COMPLETED", "REJECTED", "FAILED", "ABANDONED"):
        val = getattr(engagement_status, name)
        assert isinstance(val, str) and val, f"{name} must be a non-empty string"


def test_terminal_is_frozenset_of_non_running_statuses() -> None:
    assert isinstance(engagement_status.TERMINAL, frozenset)
    assert engagement_status.RUNNING not in engagement_status.TERMINAL
    for s in (engagement_status.COMPLETED, engagement_status.REJECTED,
              engagement_status.FAILED, engagement_status.ABANDONED):
        assert s in engagement_status.TERMINAL


def test_terminal_contains_exactly_four_statuses() -> None:
    assert len(engagement_status.TERMINAL) == 4


def test_all_status_values_are_distinct() -> None:
    statuses = [
        engagement_status.RUNNING,
        engagement_status.COMPLETED,
        engagement_status.REJECTED,
        engagement_status.FAILED,
        engagement_status.ABANDONED,
    ]
    assert len(statuses) == len(set(statuses))


# ---------------------------------------------------------------------------
# Await phase
# ---------------------------------------------------------------------------

def test_await_constants_are_non_empty_strings() -> None:
    for name in ("AWAIT_NONE", "AWAIT_PLAN", "AWAIT_COMMITTEE_GATE", "AWAIT_LOOP_GATE"):
        val = getattr(engagement_status, name)
        assert isinstance(val, str) and val, f"{name} must be a non-empty string"


def test_await_values_are_distinct() -> None:
    phases = [
        engagement_status.AWAIT_NONE,
        engagement_status.AWAIT_PLAN,
        engagement_status.AWAIT_COMMITTEE_GATE,
        engagement_status.AWAIT_LOOP_GATE,
    ]
    assert len(phases) == len(set(phases))


def test_await_none_is_a_falsy_phase_sentinel() -> None:
    # AWAIT_NONE semantically means "not blocked"; AWAIT_PLAN / _GATE / _LOOP_GATE
    # all indicate the pipeline is waiting on an operator decision.
    active_phases = {
        engagement_status.AWAIT_PLAN,
        engagement_status.AWAIT_COMMITTEE_GATE,
        engagement_status.AWAIT_LOOP_GATE,
    }
    assert engagement_status.AWAIT_NONE not in active_phases


# ---------------------------------------------------------------------------
# Gate kinds
# ---------------------------------------------------------------------------

def test_gate_kind_constants_are_non_empty_strings() -> None:
    for name in ("GATE_KIND_ELEMENT", "GATE_KIND_STEP", "GATE_KIND_TOOL"):
        val = getattr(engagement_status, name)
        assert isinstance(val, str) and val, f"{name} must be a non-empty string"


def test_gate_kinds_frozenset_matches_individual_constants() -> None:
    assert engagement_status.GATE_KINDS == frozenset({
        engagement_status.GATE_KIND_ELEMENT,
        engagement_status.GATE_KIND_STEP,
        engagement_status.GATE_KIND_TOOL,
    })


def test_gate_kinds_has_three_members() -> None:
    assert len(engagement_status.GATE_KINDS) == 3


def test_gate_kind_membership_check() -> None:
    assert "element" in engagement_status.GATE_KINDS
    assert "step" in engagement_status.GATE_KINDS
    assert "tool" in engagement_status.GATE_KINDS
    assert "bogus" not in engagement_status.GATE_KINDS


# ---------------------------------------------------------------------------
# runner re-exports AWAIT_* for backward-compat callers
# ---------------------------------------------------------------------------

def test_runner_reexports_await_constants() -> None:
    from athena.server import runner
    assert runner.AWAIT_NONE == engagement_status.AWAIT_NONE
    assert runner.AWAIT_PLAN == engagement_status.AWAIT_PLAN
    assert runner.AWAIT_COMMITTEE_GATE == engagement_status.AWAIT_COMMITTEE_GATE
    assert runner.AWAIT_LOOP_GATE == engagement_status.AWAIT_LOOP_GATE
