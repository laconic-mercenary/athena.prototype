"""Tests for the Planning committee using FakeBackend."""

import json
import textwrap
from pathlib import Path

import pytest

from athena.config import load_config
from athena.committees.planning import run_planning_committee
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.schemas import ActionPriority, ReconArtifact


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
          - config: ./agents/recon/rest_expert.yml
          - config: ./agents/recon/apache_expert.yml

      planning:
        model: claude-haiku-4-5
        leader:
          config: ./agents/planning/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/planning/network_planner.yml
          - config: ./agents/planning/web_planner.yml
""")

RECON_ARTIFACT_JSON = json.dumps({
    "artifact_id": "recon-art-001",
    "run_id": "run-001",
    "committee": "recon",
    "created_at": "2026-07-01T00:00:00Z",
    "target": "target",
    "specialists": [{"id": "spec-001", "title": "Recon Leader"}],
    "observations": [
        {
            "id": "obs-001",
            "specialist_id": "spec-001",
            "command": "nmap_scan target",
            "command_output": "22/tcp open ssh, 80/tcp open http",
            "classification": "signal_info",
            "category": "network",
            "comments": [],
        },
        {
            "id": "obs-002",
            "specialist_id": "spec-001",
            "command": "http_get http://target/files/credentials.json",
            "command_output": '{"username": "admin", "password": "secret"}',
            "classification": "signal_warn",
            "category": "exposure",
            "comments": [],
        },
    ],
    "summary": "SSH and HTTP open. Credentials exposed at /files/credentials.json.",
})

NETWORK_ACTIONS = json.dumps([
    {
        "priority": "high",
        "title": "SSH credential reuse test",
        "category": "credential_access",
        "description": "Attempt SSH login with credentials from /files/credentials.json",
        "rationale": "Credentials exposed in obs-002; SSH open in obs-001",
        "observation_ids": ["obs-001", "obs-002"],
    }
])

WEB_ACTIONS = json.dumps([
    {
        "priority": "critical",
        "title": "credentials.json full retrieval",
        "category": "exposure",
        "description": "Download and document the full credentials.json file",
        "rationale": "Plaintext credentials found at /files/credentials.json (obs-002)",
        "observation_ids": ["obs-002"],
    }
])

PLAN_ARTIFACT_JSON = json.dumps({
    "actions": [
        {
            "priority": "critical",
            "title": "credentials.json full retrieval",
            "category": "exposure",
            "description": "Download and document credentials.json",
            "rationale": "Plaintext creds at /files/credentials.json",
            "observation_ids": ["obs-002"],
        },
        {
            "priority": "high",
            "title": "SSH credential reuse test",
            "category": "credential_access",
            "description": "Attempt SSH with discovered credentials",
            "rationale": "SSH open; credentials found",
            "observation_ids": ["obs-001", "obs-002"],
        },
    ],
    "summary": "Credential exposure is the critical path. SSH testing follows.",
})


@pytest.fixture
def config(tmp_path: Path):
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(VALID_YAML)
    return load_config(cfg_file)


@pytest.fixture
def recon_artifact():
    return ReconArtifact.model_validate_json(RECON_ARTIFACT_JSON)


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool_call(name: str, inp: dict, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=inp)],
    )


def test_returns_valid_plan_artifact(config, recon_artifact) -> None:
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_planner"}, "tc1"),
            _tool_call("summon_specialist", {"name": "web_planner"}, "tc2"),
            _end(PLAN_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(NETWORK_ACTIONS)]),
        FakeBackend([_end(WEB_ACTIONS)]),
    ])

    artifact = run_planning_committee(
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert artifact.run_id == recon_artifact.run_id
    assert artifact.target == "target"
    assert artifact.recon_artifact_id == recon_artifact.artifact_id
    assert len(artifact.actions) == 2
    assert artifact.actions[0].priority == ActionPriority.critical


def test_recon_artifact_injected_into_specialist_initial_message(config, recon_artifact) -> None:
    """Each specialist backend should receive the ReconArtifact JSON in its initial message."""
    network_backend = FakeBackend([_end(NETWORK_ACTIONS)])
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_planner"}, "tc1"),
            _end(PLAN_ARTIFACT_JSON),
        ]),
        network_backend,
    ])

    run_planning_committee(
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert "ReconArtifact" in network_backend.initial_message
    assert recon_artifact.artifact_id in network_backend.initial_message


def test_plan_links_to_recon_artifact(config, recon_artifact) -> None:
    backends = iter([
        FakeBackend([_end(PLAN_ARTIFACT_JSON)]),
    ])

    artifact = run_planning_committee(
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert artifact.recon_artifact_id == recon_artifact.artifact_id


def test_action_ids_assigned_by_python(config, recon_artifact) -> None:
    """Actions must have Python-assigned IDs, not LLM-generated ones."""
    backends = iter([
        FakeBackend([_end(PLAN_ARTIFACT_JSON)]),
    ])

    artifact = run_planning_committee(
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    for action in artifact.actions:
        assert action.id  # non-empty
        assert len(action.id) == 8  # new_short_id() format


def test_invalid_priority_raises(config, recon_artifact) -> None:
    bad_plan = json.dumps({
        "actions": [{"priority": "BOGUS", "category": "x", "description": "y", "rationale": "z"}],
        "summary": "done",
    })
    backends = iter([FakeBackend([_end(bad_plan)])])

    with pytest.raises(Exception):
        run_planning_committee(
            recon_artifact=recon_artifact,
            config=config,
            _backend_factory=lambda p, u=None: next(backends),
        )
