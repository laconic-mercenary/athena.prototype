"""Tests for the private-catalog ensemble resolver: a named ensemble resolves against the
project's private catalog first, no name falls back to the public ATHENA_ENS_PATH, and a
name absent from the catalog raises rather than silently running the public ensemble.
"""

import pytest

from athena import env_vars
from athena.server import runner


def test_no_name_falls_back_to_public_ens_path(monkeypatch, tmp_path) -> None:
    public = tmp_path / "public_ensemble"
    monkeypatch.setenv(env_vars.ENS_PATH, str(public))
    assert runner._resolve_ensemble_path("default", None) == public


def test_named_ensemble_resolves_from_private_catalog(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    private = tmp_path / "proj" / "ensembles" / "foo"
    private.mkdir(parents=True)
    assert runner._resolve_ensemble_path("proj", "foo") == private


def test_named_ensemble_absent_raises_not_found(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(env_vars.SRV_PROJECTS_DIR, str(tmp_path))
    with pytest.raises(runner.EnsembleNotFound):
        runner._resolve_ensemble_path("proj", "missing")
