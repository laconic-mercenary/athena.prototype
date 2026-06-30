"""Configuration loading for the Athena prototype."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_ARTIFACTS_DIR = Path("artifacts")
DEFAULT_TARGET_HOST = "target"
DEFAULT_MAX_AGENT_ITERATIONS = 8


@dataclass(frozen=True)
class AthenaConfig:
    """Runtime configuration for a local Athena run."""

    artifacts_dir: Path
    target_host: str
    max_agent_iterations: int


def load_config() -> AthenaConfig:
    """Return the default local configuration for the initial scaffold."""

    return AthenaConfig(
        artifacts_dir=DEFAULT_ARTIFACTS_DIR,
        target_host=DEFAULT_TARGET_HOST,
        max_agent_iterations=DEFAULT_MAX_AGENT_ITERATIONS,
    )
