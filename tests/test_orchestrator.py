"""Tests for the two-phase orchestrator."""

import json
import textwrap
from pathlib import Path

import pytest

from athena.config import load_config
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.orchestrator import RunRejected, run_orchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_YAML = textwrap.dedent("""
    artifacts_dir: {artifacts_dir}
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
          - config: ./agents/recon/rest_expert.yml
          - config: ./agents/recon/apache_expert.yml
""")


@pytest.fixture
def config(tmp_path: Path):
    artifacts_dir = tmp_path / "artifacts"
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(VALID_YAML.format(artifacts_dir=str(artifacts_dir)))
    return load_config(cfg_file)


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool_call(name: str, inp: dict, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=inp)],
    )


APPROVAL_JSON = json.dumps({"target": "target", "notes": "Local authorized probe."})

RECON_ARTIFACT_JSON = json.dumps({
    "observations": [
        {
            "specialist_id": "abc",
            "command": "nmap_scan",
            "command_output": "80/tcp open",
            "classification": "signal_info",
            "category": "network",
            "comments": [],
        }
    ],
    "summary": "HTTP open on port 80.",
})

SCOUT_FINDINGS = json.dumps([
    {"command": "nmap_scan target", "command_output": "80/tcp open http", "notes": "HTTP open"},
])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_approval_path_returns_approval(config) -> None:
    backends = iter([
        FakeBackend([_end(APPROVAL_JSON)]),        # orchestrator
        FakeBackend([                              # recon leader
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _end(RECON_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(SCOUT_FINDINGS)]),       # network scout
    ])

    result = run_orchestrator(
        instructions="Probe the target container.",
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert result is not None
    assert result.target == "target"
    assert result.notes == "Local authorized probe."


def test_approval_path_writes_artifacts(config, tmp_path) -> None:
    backends = iter([
        FakeBackend([_end(APPROVAL_JSON)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _end(RECON_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(SCOUT_FINDINGS)]),
    ])

    result = run_orchestrator(
        instructions="Probe the target.",
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert result is not None
    run_dir = config.artifacts_dir / result.run_id
    assert (run_dir / "run.log").exists()
    assert (run_dir / "approval.json").exists()
    assert (run_dir / "recon.json").exists()

    log_text = (run_dir / "run.log").read_text()
    for event in ["run started", "recon committee summoned", "recon artifact emitted", "run completed"]:
        assert event in log_text


def test_rejection_returns_none(config) -> None:
    backends = iter([
        FakeBackend([
            _tool_call("reject_run", {"reason": "Instructions target an external system."}, "tc1"),
        ]),
    ])

    result = run_orchestrator(
        instructions="Hack example.com",
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert result is None


def test_ask_user_interaction(config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator asks a question, gets an answer, then approves."""
    monkeypatch.setattr("builtins.input", lambda _: "target")

    backends = iter([
        FakeBackend([
            _tool_call("ask_user", {"question": "What is the target hostname?"}, "tc1"),
            _end(APPROVAL_JSON),
        ]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc2"),
            _end(RECON_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(SCOUT_FINDINGS)]),
    ])

    result = run_orchestrator(
        instructions="Probe something.",
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert result is not None
    assert result.target == "target"


def test_recon_json_is_valid_pydantic(config, tmp_path) -> None:
    """The written recon.json can be parsed back into a ReconArtifact."""
    from athena.schemas import ReconArtifact

    backends = iter([
        FakeBackend([_end(APPROVAL_JSON)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _end(RECON_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(SCOUT_FINDINGS)]),
    ])

    result = run_orchestrator(
        instructions="Probe the target.",
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert result is not None
    recon_path = config.artifacts_dir / result.run_id / "recon.json"
    artifact = ReconArtifact.model_validate_json(recon_path.read_text())
    assert artifact.target == "target"
    assert len(artifact.observations) == 1
