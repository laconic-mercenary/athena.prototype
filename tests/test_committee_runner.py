"""Tests for _run_element compare mode and the specialist runner."""

import threading

import pytest

from athena.ensemble.types import LoadedElement, LoadedSpecialist
from athena.harness.committee_runner import _run_element, _variant_label
from athena.model_backend import FakeBackend, ModelResponse


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _specialist(id_: str, model: str = "test-model", temperature: float | None = None) -> LoadedSpecialist:
    return LoadedSpecialist(
        id=id_, system="you are a test specialist",
        model=model, provider="fake", temperature=temperature,
    )


def _element(specialists: list[LoadedSpecialist], mode: str = "combine") -> LoadedElement:
    return LoadedElement(id="test_elem", instances=1, specialists=specialists, skill_ids=[], mode=mode)


def _thread_safe_factory(backends: list[FakeBackend]):
    """Return backends in order, thread-safely."""
    lock = threading.Lock()
    idx = [0]

    def factory(provider: str, url=None) -> FakeBackend:
        with lock:
            b = backends[idx[0] % len(backends)]
            idx[0] += 1
            return b

    return factory


# ---------------------------------------------------------------------------
# Single-specialist path (backward compat)
# ---------------------------------------------------------------------------

def test_single_specialist_returns_output() -> None:
    backend = FakeBackend([_end("result text")])
    element = _element([_specialist("spec1")])
    result = _run_element(element, "do the task", {}, "comm", "run1", "t1", lambda p, u=None: backend)
    assert result == "result text"


def test_single_specialist_temperature_passed_to_backend() -> None:
    backend = FakeBackend([_end("ok")])
    element = _element([_specialist("spec1", temperature=0.3)])
    _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None: backend)
    assert backend.calls[0]["temperature"] == 0.3


def test_single_specialist_no_temperature_passes_none() -> None:
    backend = FakeBackend([_end("ok")])
    element = _element([_specialist("spec1")])  # no temperature
    _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None: backend)
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
    factory = _thread_safe_factory([FakeBackend([_end("A")]), FakeBackend([_end("B")])])
    element = _element([_specialist("conservative", temperature=0.2), _specialist("lateral", temperature=0.9)], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", factory)
    assert "Variant 1" in result
    assert "Variant 2" in result
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


def test_compare_mode_single_specialist_returns_plain_output() -> None:
    # compare mode with one specialist: no variant labels, just the raw output
    backend = FakeBackend([_end("plain result")])
    element = _element([_specialist("s1", temperature=0.5)], mode="compare")
    result = _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None: backend)
    assert result == "plain result"
    assert "Variant" not in result


# ---------------------------------------------------------------------------
# Combine + multiple specialists: not yet implemented
# ---------------------------------------------------------------------------

def test_combine_mode_multiple_specialists_raises() -> None:
    element = _element([_specialist("s1"), _specialist("s2")], mode="combine")
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        _run_element(element, "task", {}, "comm", "run1", "t1", lambda p, u=None: FakeBackend([]))


# ---------------------------------------------------------------------------
# _variant_label
# ---------------------------------------------------------------------------

def test_variant_label_shows_temperature() -> None:
    s = _specialist("conservative", temperature=0.2)
    label = _variant_label(s, 0, ["test-model"])
    assert "t=0.2" in label
    assert "Variant 1" in label
    assert "conservative" in label


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


def test_variant_label_index_is_one_based() -> None:
    s = _specialist("s1")
    assert _variant_label(s, 0, ["m"]).startswith("Variant 1")
    assert _variant_label(s, 2, ["m"]).startswith("Variant 3")
