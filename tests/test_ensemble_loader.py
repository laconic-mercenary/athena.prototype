"""Tests for ensemble/loader.py — uses the fsscanv1 fixture ensemble."""

from pathlib import Path

import pytest

from athena.ensemble.loader import load_ensemble
from athena.ensemble.types import LoadedEnsemble

FIXTURE = Path(__file__).parent / "ensembles" / "fsscanv1"


def test_load_ensemble_returns_loaded_ensemble():
    ensemble = load_ensemble(FIXTURE)
    assert isinstance(ensemble, LoadedEnsemble)


def test_load_ensemble_name_and_version():
    ensemble = load_ensemble(FIXTURE)
    assert ensemble.name == "inventory"
    assert ensemble.version == "1.0.0"


def test_load_ensemble_entry():
    ensemble = load_ensemble(FIXTURE)
    assert ensemble.entry == "scan"


def test_load_ensemble_committees():
    ensemble = load_ensemble(FIXTURE)
    assert "scan" in ensemble.committees
    assert "report" in ensemble.committees


def test_load_ensemble_skills():
    ensemble = load_ensemble(FIXTURE)
    assert "count_regular_files" in ensemble.skills
    assert "count_hidden_files" in ensemble.skills


def test_load_ensemble_workflow_nodes():
    ensemble = load_ensemble(FIXTURE)
    assert "scan" in ensemble.workflow
    assert "report" in ensemble.workflow


def test_load_ensemble_workflow_transitions():
    ensemble = load_ensemble(FIXTURE)
    scan_node = ensemble.workflow["scan"]
    targets = {(t.to, t.condition) for t in scan_node.transitions}
    assert ("report", None) in targets
    assert ("scan", "retry") in targets


def test_load_ensemble_output_schema_patched():
    ensemble = load_ensemble(FIXTURE)
    # The loader patches output_schema from the workflow node onto the committee.
    scan_schema = ensemble.committees["scan"].output_schema
    assert scan_schema is not object  # was patched from the placeholder


def test_load_ensemble_elements():
    ensemble = load_ensemble(FIXTURE)
    scan = ensemble.committees["scan"]
    element_ids = {e.id for e in scan.elements}
    assert "count_regular_files" in element_ids
    assert "count_hidden_files" in element_ids


def test_load_ensemble_compare_element_has_multiple_specialists():
    ensemble = load_ensemble(FIXTURE)
    scan = ensemble.committees["scan"]
    hidden = next(e for e in scan.elements if e.id == "count_hidden_files")
    assert len(hidden.specialists) == 2


def test_load_ensemble_missing_manifest_raises():
    with pytest.raises(ValueError, match="No manifest.yml"):
        load_ensemble(Path("/nonexistent/path"))


def test_load_ensemble_consumes_required():
    ensemble = load_ensemble(FIXTURE)
    report = ensemble.committees["report"]
    assert "scan" in report.consumes_required


def test_load_ensemble_capability_loaded():
    ensemble = load_ensemble(FIXTURE)
    assert len(ensemble.capability) > 0
