"""Tests for _run_element compare mode and the specialist runner."""

import threading

import pytest

from athena.ensemble.types import LoadedElement, LoadedSpecialist
from athena.harness.committee_runner import _resolve_winner, _run_element, _variant_label
from athena.model_backend import FakeBackend, ModelResponse


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _specialist(id_: str, model: str = "test-model", temperature: float | None = None) -> LoadedSpecialist:
    return LoadedSpecialist(
        id=id_, title=id_, system="you are a test specialist",
        model=model, provider="fake", temperature=temperature, skill_ids=[],
        max_tokens=None,
    )


def _element(specialists: list[LoadedSpecialist], mode: str = "combine") -> LoadedElement:
    # `mode` is accepted for call-compatibility but no longer a field — compare vs
    # single is now decided by specialist count.
    return LoadedElement(id="test_elem", label="Test Element", instances=1, specialists=specialists, skill_ids=[])


def _thread_safe_factory(backends: list[FakeBackend]):
    """Return backends in order, thread-safely."""
    lock = threading.Lock()
    idx = [0]

    def factory(provider: str, url=None, extra_headers=None) -> FakeBackend:
        with lock:
            b = backends[idx[0] % len(backends)]
            idx[0] += 1
            return b

    return factory


# ---------------------------------------------------------------------------
# Single-specialist path (backward compat)
# ---------------------------------------------------------------------------

def _planning_sinks() -> dict:
    # Mirrors the Planning committee: mixed models → verbose "model=" suffix labels.
    return {
        "exploit_planner": {
            "Exploit Planner A (t=0.3, model=claude-haiku-4-5-20251001)": {"output": "a", "title": "Exploit Planner A"},
            "Exploit Planner B (t=0.7, model=claude-haiku-4-5-20251001)": {"output": "b", "title": "Exploit Planner B"},
            "Foundation-Sec Planner (model=foundation-sec-8b)": {"output": "f", "title": "Foundation-Sec Planner"},
        }
    }


def test_resolve_winner_exact() -> None:
    sinks = _planning_sinks()
    label = "Exploit Planner B (t=0.7, model=claude-haiku-4-5-20251001)"
    assert _resolve_winner(label, sinks) == ("exploit_planner", label)


def test_resolve_winner_title_only_dropped_meta() -> None:
    # The common LLM failure: it echoes just the title, no "(t=…, model=…)" suffix.
    sinks = _planning_sinks()
    assert _resolve_winner("Exploit Planner A", sinks) == (
        "exploit_planner",
        "Exploit Planner A (t=0.3, model=claude-haiku-4-5-20251001)",
    )


def test_resolve_winner_case_insensitive() -> None:
    sinks = _planning_sinks()
    assert _resolve_winner("foundation-sec planner", sinks) == (
        "exploit_planner",
        "Foundation-Sec Planner (model=foundation-sec-8b)",
    )


def test_resolve_winner_unknown_returns_none() -> None:
    sinks = _planning_sinks()
    assert _resolve_winner("Some Other Variant", sinks) is None
    assert _resolve_winner("", sinks) is None


def test_single_specialist_returns_output() -> None:
    backend = FakeBackend([_end("result text")])
    element = _element([_specialist("spec1")])
    result = _run_element(element, "do the task", {}, "comm", "run1", "t1", lambda p, u=None, *_: backend)
    assert result == "result text"


def test_single_specialist_temperature_passed_to_backend() -> None:
    backend = FakeBackend([_end("ok")])
    element = _element([_specialist("spec1", temperature=0.3)])
    _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None, *_: backend)
    assert backend.calls[0]["temperature"] == 0.3


def test_single_specialist_no_temperature_passes_none() -> None:
    backend = FakeBackend([_end("ok")])
    element = _element([_specialist("spec1")])  # no temperature
    _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None, *_: backend)
    assert backend.calls[0]["temperature"] is None


# ---------------------------------------------------------------------------
# Compare mode: multi-specialist
# ---------------------------------------------------------------------------

def test_compare_mode_runs_all_specialists() -> None:
    backend_a = FakeBackend([_end("alpha output")])
    backend_b = FakeBackend([_end("beta output")])
    factory = _thread_safe_factory([backend_a, backend_b])
    element = _element([_specialist("conservative", temperature=0.2), _specialist("lateral", temperature=0.9)], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", factory)
    assert "alpha output" in result
    assert "beta output" in result


def test_compare_mode_output_contains_variant_labels() -> None:
    # Variant labels are title-based (e.g. "conservative (t=0.2)"), per fs-scan leader.yml.
    factory = _thread_safe_factory([FakeBackend([_end("A")]), FakeBackend([_end("B")])])
    element = _element([_specialist("conservative", temperature=0.2), _specialist("lateral", temperature=0.9)], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", factory)
    assert "conservative" in result
    assert "lateral" in result


def test_compare_mode_output_contains_temperatures() -> None:
    factory = _thread_safe_factory([FakeBackend([_end("A")]), FakeBackend([_end("B")])])
    element = _element([_specialist("s1", temperature=0.2), _specialist("s2", temperature=0.9)], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", factory)
    assert "t=0.2" in result
    assert "t=0.9" in result


def test_compare_mode_output_contains_selection_note() -> None:
    factory = _thread_safe_factory([FakeBackend([_end("A")]), FakeBackend([_end("B")])])
    element = _element([_specialist("s1"), _specialist("s2")], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", factory)
    assert "Select the variant" in result


# ---------------------------------------------------------------------------
# Compare mode: fault tolerance (one specialist failing must not sink the element)
# ---------------------------------------------------------------------------

def _max_tokens() -> ModelResponse:
    # run_agent raises RuntimeError when a model stops on max_tokens — simulates a
    # specialist (e.g. Foundation-Sec) exhausting its output budget.
    return ModelResponse(stop_reason="max_tokens", text=None)


def test_compare_mode_survives_one_specialist_failure() -> None:
    # One specialist raises, the other succeeds. Which backend each parallel worker
    # receives is race-dependent, but exactly one survives and its output must come back.
    good = FakeBackend([_end("survivor output")])
    bad = FakeBackend([_max_tokens()])
    factory = _thread_safe_factory([good, bad])
    element = _element([_specialist("s1"), _specialist("s2")], mode="compare")

    failures: list[dict] = []
    from pubsub import pub
    # Named params (not **kwargs) so pubsub infers a matching arg spec for the topic.
    def _on_failed(run_id=None, committee=None, agent_id=None, error=None):
        failures.append({"run_id": run_id, "committee": committee, "agent_id": agent_id, "error": error})
    pub.subscribe(_on_failed, "agent.failed")
    try:
        result = _run_element(element, "task", {}, "comm", "run1", "t1", factory)
    finally:
        pub.unsubscribe(_on_failed, "agent.failed")

    assert "survivor output" in result          # survivor kept
    assert "Select the variant" in result       # still a valid compare prompt
    assert len(failures) == 1                    # exactly one agent.failed emitted
    assert failures[0].get("error")              # carries an error string


def test_compare_mode_all_specialists_fail_raises() -> None:
    factory = _thread_safe_factory([FakeBackend([_max_tokens()]), FakeBackend([_max_tokens()])])
    element = _element([_specialist("s1"), _specialist("s2")], mode="compare")
    with pytest.raises(RuntimeError, match="failed"):
        _run_element(element, "task", {}, "comm", "run1", "t1", factory)


def test_compare_mode_single_specialist_returns_plain_output() -> None:
    # compare mode with one specialist: no variant labels, just the raw output
    backend = FakeBackend([_end("plain result")])
    element = _element([_specialist("s1", temperature=0.5)], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None, *_: backend)
    assert result == "plain result"
    assert "Variant" not in result


# ---------------------------------------------------------------------------
# _variant_label
# ---------------------------------------------------------------------------

def test_variant_label_shows_temperature() -> None:
    s = _specialist("conservative", temperature=0.2)
    label = _variant_label(s, 0, ["test-model"])
    assert "t=0.2" in label
    assert "conservative" in label  # title-based label


def test_variant_label_omits_temperature_when_none() -> None:
    s = _specialist("s1")  # no temperature
    label = _variant_label(s, 0, ["test-model"])
    assert "t=" not in label


def test_variant_label_shows_model_when_diverse() -> None:
    s = _specialist("s1", model="model-a")
    label = _variant_label(s, 0, ["model-a", "model-b"])
    assert "model=model-a" in label


def test_variant_label_omits_model_when_uniform() -> None:
    s = _specialist("s1", model="model-a")
    label = _variant_label(s, 0, ["model-a", "model-a"])
    assert "model=" not in label


def test_variant_label_leads_with_title() -> None:
    s = _specialist("recon_expert")
    assert _variant_label(s, 0, ["m"]).startswith("recon_expert")
