"""Artifact and run logging.

RunLogger owns a named logger (athena.run.<run_id>) with a FileHandler that
writes to artifacts/<run_id>/run.log. Lifecycle events propagate up to the
athena stream handler for stdout output automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path

from athena.logging_setup import UTC_FORMATTER


class RunLogger:
    def __init__(self, run_id: str, artifacts_dir: Path) -> None:
        self._run_dir = artifacts_dir / run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger(f"athena.run.{run_id}")
        # File handler writes to run.log alongside the JSON artifacts.
        fh = logging.FileHandler(self._run_dir / "run.log")
        fh.setFormatter(UTC_FORMATTER)
        self._logger.addHandler(fh)
        # propagate=True (default) means messages also reach the athena stream handler.

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def log(self, event: str) -> None:
        self._logger.info(event)

    def write_artifact(self, name: str, content: str) -> Path:
        """Write a JSON string to artifacts/<run_id>/<name>.json."""
        path = self._run_dir / f"{name}.json"
        path.write_text(content)
        return path
