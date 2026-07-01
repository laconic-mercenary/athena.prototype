"""Tests for artifact and run logging."""

import logging
from pathlib import Path

import pytest

from athena.artifacts import RunLogger


@pytest.fixture(autouse=True)
def athena_logger():
    """Ensure the athena logger has a handler so propagation works in tests."""
    logger = logging.getLogger("athena")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.DEBUG)
    yield


def test_log_creates_run_log(tmp_path: Path) -> None:
    logger = RunLogger("run-001", tmp_path)
    logger.log("run started")
    log_text = (tmp_path / "run-001" / "run.log").read_text()
    assert "run started" in log_text


def test_log_entries_are_timestamped(tmp_path: Path) -> None:
    logger = RunLogger("run-001", tmp_path)
    logger.log("recon committee summoned")
    line = (tmp_path / "run-001" / "run.log").read_text().strip()
    # Expect: 2026-07-01T...Z  athena.run.run-001  recon committee summoned
    assert "T" in line and "Z" in line


def test_multiple_log_entries_appended(tmp_path: Path) -> None:
    logger = RunLogger("run-002", tmp_path)
    logger.log("run started")
    logger.log("recon committee summoned")
    logger.log("run completed")
    lines = (tmp_path / "run-002" / "run.log").read_text().strip().splitlines()
    assert len(lines) == 3


def test_write_artifact_creates_json_file(tmp_path: Path) -> None:
    logger = RunLogger("run-003", tmp_path)
    path = logger.write_artifact("recon", '{"summary": "done"}')
    assert path.exists()
    assert path.name == "recon.json"
    assert path.read_text() == '{"summary": "done"}'


def test_run_dir_created_automatically(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "artifacts"
    logger = RunLogger("abc123", nested)
    logger.log("started")
    assert (nested / "abc123" / "run.log").exists()
