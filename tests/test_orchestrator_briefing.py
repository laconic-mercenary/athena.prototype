"""Regression tests for OrchestratorHarness.run_briefing() input robustness.

A malformed submit_plan (plan passed as a string or non-object) previously crashed the
whole engagement at `dict(tc.input.get("plan"))` with a ValueError. run_briefing must
re-prompt instead of crashing.
"""

import pytest

from athena.harness.orchestrator import OrchestratorHarness
from athena.model_backend import FakeBackend, ModelResponse, ToolCall

_VALID_PLAN = {
    "operator_instructions": "count the files",
    "committees": {"scan": {"objective": ["count regular and hidden files"]}},
}


def _submit_plan(plan, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name="submit_plan", input={"plan": plan})],
    )


def _harness(backend: FakeBackend) -> OrchestratorHarness:
    orch = OrchestratorHarness(
        backend=backend, model="m", run_id="run1",
        ask_user_handler=lambda q: "", read_artifact_fn=lambda n: "",
    )
    orch.start_briefing(ensemble_name="e", version="1", capability="cap", operator_message="msg")
    return orch


def test_string_plan_is_reprompted_not_crashed() -> None:
    # First submit_plan passes a bare string (the exact crash case); the harness must
    # reject it and re-prompt, then accept the valid object on the next turn.
    backend = FakeBackend([
        _submit_plan("this is not an object", "p1"),
        _submit_plan(_VALID_PLAN, "p2"),
    ])
    plan = _harness(backend).run_briefing()
    assert plan.engagement_id == "run1"
    assert "scan" in plan.committees
    assert len(backend.calls) == 2  # rejected once, then accepted


def test_list_plan_is_reprompted_not_crashed() -> None:
    backend = FakeBackend([
        _submit_plan(["not", "an", "object"], "p1"),
        _submit_plan(_VALID_PLAN, "p2"),
    ])
    plan = _harness(backend).run_briefing()
    assert plan.engagement_id == "run1"


def test_json_string_plan_is_coerced() -> None:
    import json
    # A plan delivered as a JSON *string* of an object is coerced and accepted.
    backend = FakeBackend([_submit_plan(json.dumps(_VALID_PLAN), "p1")])
    plan = _harness(backend).run_briefing()
    assert plan.engagement_id == "run1"
    assert "scan" in plan.committees
    assert len(backend.calls) == 1  # accepted on the first turn


def test_valid_object_plan_still_works() -> None:
    backend = FakeBackend([_submit_plan(_VALID_PLAN, "p1")])
    plan = _harness(backend).run_briefing()
    assert plan.engagement_id == "run1"
