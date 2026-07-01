import textwrap
from pathlib import Path

import pytest

from athena.config import load_config


VALID_YAML = textwrap.dedent("""
    artifacts_dir: ./artifacts
    max_agent_iterations: 8

    model:
      default: claude-haiku-4-5
      provider: anthropic

    orchestrator:
      model: claude-sonnet-4-6
      config: ./agents/orchestrator.yml

    committees:
      recon:
        model: claude-haiku-4-5
        leader:
          config: ./agents/recon/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/recon/network_scout.yml
          - config: ./agents/recon/ssh_expert.yml
            model: claude-haiku-4-5
""")


def test_load_config_parses_valid_yaml(tmp_path: Path) -> None:
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(VALID_YAML)

    config = load_config(cfg_file)

    assert config.artifacts_dir == Path("./artifacts")
    assert config.max_agent_iterations == 8
    assert config.model.default == "claude-haiku-4-5"
    assert config.model.provider == "anthropic"
    assert config.model.ollama_base_url is None
    assert config.orchestrator.model == "claude-sonnet-4-6"
    assert config.orchestrator.provider is None
    assert config.orchestrator.config_path == Path("./agents/orchestrator.yml")
    assert "recon" in config.committees
    recon = config.committees["recon"]
    assert recon.model == "claude-haiku-4-5"
    assert recon.leader.config_path == Path("./agents/recon/leader.yml")
    assert recon.leader.model == "claude-sonnet-4-6"
    assert len(recon.specialists) == 2
    assert recon.specialists[0].model is None
    assert recon.specialists[1].model == "claude-haiku-4-5"


@pytest.mark.parametrize("missing_key,yaml_override", [
    ("artifacts_dir", "artifacts_dir: ~\n"),
    ("model", ""),
    ("orchestrator", ""),
    ("committees", ""),
    ("provider", "provider: ~\n"),
])
def test_load_config_raises_on_missing_required_field(
    tmp_path: Path, missing_key: str, yaml_override: str
) -> None:
    broken = VALID_YAML.replace(
        f"{missing_key}:", f"_removed_{missing_key}:"
    )
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(broken)

    with pytest.raises((ValueError, AttributeError)):
        load_config(cfg_file)
