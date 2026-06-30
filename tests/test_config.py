from pathlib import Path

from athena.config import load_config


def test_load_config_returns_default_local_settings() -> None:
    config = load_config()

    assert config.artifacts_dir == Path("artifacts")
    assert config.target_host == "target"
    assert config.max_agent_iterations == 8
