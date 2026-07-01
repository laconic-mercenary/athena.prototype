"""Configuration loading for the Athena prototype."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelConfig:
    default: str
    provider: str              # "anthropic" | "ollama"
    ollama_base_url: str | None  # required when provider == "ollama"


@dataclass(frozen=True)
class OrchestratorConfig:
    model: str
    provider: str | None       # None → inherit from ModelConfig.provider
    config_path: Path


@dataclass(frozen=True)
class SpecialistConfig:
    config_path: Path
    model: str | None          # None → inherit from CommitteeConfig.model
    provider: str | None       # None → inherit from CommitteeConfig.provider


@dataclass(frozen=True)
class CommitteeLeaderConfig:
    config_path: Path
    model: str | None          # None → inherit from CommitteeConfig.model
    provider: str | None       # None → inherit from CommitteeConfig.provider


@dataclass(frozen=True)
class CommitteeConfig:
    model: str
    provider: str | None       # None → inherit from ModelConfig.provider
    leader: CommitteeLeaderConfig
    specialists: tuple[SpecialistConfig, ...]


@dataclass(frozen=True)
class AthenaConfig:
    artifacts_dir: Path
    max_agent_iterations: int
    model: ModelConfig
    orchestrator: OrchestratorConfig
    committees: dict[str, CommitteeConfig]


def _require(mapping: dict, key: str, context: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing required config field '{key}' under '{context}'")
    return mapping[key]


def load_config(path: Path) -> AthenaConfig:
    """Load and validate configuration from a YAML file."""
    raw: dict = yaml.safe_load(path.read_text())

    model_raw = _require(raw, "model", "root")
    model = ModelConfig(
        default=_require(model_raw, "default", "model"),
        provider=_require(model_raw, "provider", "model"),
        ollama_base_url=model_raw.get("ollama_base_url"),
    )

    orch_raw = _require(raw, "orchestrator", "root")
    orchestrator = OrchestratorConfig(
        model=_require(orch_raw, "model", "orchestrator"),
        provider=orch_raw.get("provider"),
        config_path=Path(_require(orch_raw, "config", "orchestrator")),
    )

    committees_raw = _require(raw, "committees", "root")
    committees: dict[str, CommitteeConfig] = {}
    for name, c in committees_raw.items():
        leader_raw = _require(c, "leader", f"committees.{name}")
        leader = CommitteeLeaderConfig(
            config_path=Path(_require(leader_raw, "config", f"committees.{name}.leader")),
            model=leader_raw.get("model"),
            provider=leader_raw.get("provider"),
        )
        specialists = tuple(
            SpecialistConfig(
                config_path=Path(_require(s, "config", f"committees.{name}.specialists")),
                model=s.get("model"),
                provider=s.get("provider"),
            )
            for s in _require(c, "specialists", f"committees.{name}")
        )
        committees[name] = CommitteeConfig(
            model=_require(c, "model", f"committees.{name}"),
            provider=c.get("provider"),
            leader=leader,
            specialists=specialists,
        )

    return AthenaConfig(
        artifacts_dir=Path(_require(raw, "artifacts_dir", "root")),
        max_agent_iterations=int(_require(raw, "max_agent_iterations", "root")),
        model=model,
        orchestrator=orchestrator,
        committees=committees,
    )
