"""End-to-end tests for the Recon committee using FakeBackend.

No live network, no LLM API calls. The FakeBackend is scripted to simulate:
  1. Leader calls summon_specialist("network_scout")
  2. Leader calls summon_specialist("rest_expert")
  3. Leader emits a ReconArtifact JSON
  Network Scout emits two RawFindings (ports 22 and 80 open).
  REST Expert emits one RawFinding (Apache found at /).
"""

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from athena.config import load_config
from athena.committees.recon import run_recon_committee
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.schemas import OrchestratorApproval


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
""")


@pytest.fixture
def config(tmp_path: Path):
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(VALID_YAML)
    return load_config(cfg_file)


@pytest.fixture
def approval() -> OrchestratorApproval:
    return OrchestratorApproval(
        target="target",
        notes="Probe the target for recon. Local authorized engagement.",
    )


# ---------------------------------------------------------------------------
# Scripted responses
# ---------------------------------------------------------------------------

def _tool_call(name: str, input: dict, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=input)],
    )


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


SCOUT_FINDINGS = [
    {"command": "nmap_scan target", "command_output": "22/tcp open ssh, 80/tcp open http", "notes": "SSH and HTTP are open"},
    {"command": "check_port target 22", "command_output": "Port target:22 is open (1.2ms)", "notes": "Port 22 confirmed open"},
]

REST_FINDINGS = [
    {"command": "http_head http://target/", "command_output": "Status: 200\nserver: Apache/2.4.52 (Ubuntu)", "notes": "Apache found at root"},
]

ARTIFACT_JSON = json.dumps({
    "observations": [
        {
            "specialist_id": "PLACEHOLDER",  # overwritten in test
            "command": "nmap_scan target",
            "command_output": "22/tcp open ssh, 80/tcp open http",
            "classification": "signal_info",
            "category": "network",
            "comments": [],
        },
        {
            "specialist_id": "PLACEHOLDER",
            "command": "http_head http://target/",
            "command_output": "Status: 200, server=Apache/2.4.52",
            "classification": "signal_info",
            "category": "service",
            "comments": [],
        },
    ],
    "summary": "Target exposes SSH on port 22 and Apache on port 80.",
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_run_recon_committee_returns_valid_artifact(config, approval, tmp_path):
    """Full committee run with scripted fake backends."""
    backends = iter([
        # Leader: summon network_scout, then summon rest_expert, then emit artifact
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _tool_call("summon_specialist", {"name": "rest_expert"}, "tc2"),
            _end(ARTIFACT_JSON),
        ]),
        # Network Scout: immediately emits findings
        FakeBackend([_end(json.dumps(SCOUT_FINDINGS))]),
        # REST Expert: immediately emits findings
        FakeBackend([_end(json.dumps(REST_FINDINGS))]),
    ])

    def fake_factory(provider: str, ollama_url=None) -> FakeBackend:
        return next(backends)

    artifact = run_recon_committee(
        approval=approval,
        config=config,
        _backend_factory=fake_factory,
    )

    assert artifact.run_id == approval.run_id
    assert artifact.target == "target"
    assert artifact.summary == "Target exposes SSH on port 22 and Apache on port 80."
    assert len(artifact.observations) == 2
    assert len(artifact.specialists) == 3  # leader + scout + rest_expert


def test_specialist_ids_are_overridden_in_python(config, approval):
    """Python enforces correct specialist_id in the tool result sent to the leader.

    The scout deliberately omits specialist_id from its output — Python must fill it
    in before the findings are returned to the leader as a tool result.
    """
    # Scout returns findings with no specialist_id field at all.
    scout_findings_no_id = [
        {"command": "nmap_scan", "command_output": "80/tcp open", "notes": "HTTP open"},
    ]

    leader_backend = FakeBackend([
        _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
        _end(json.dumps({
            "observations": [
                {
                    "specialist_id": "will-be-verified-below",
                    "command": "nmap_scan",
                    "command_output": "80/tcp open",
                    "classification": "signal_info",
                    "category": "network",
                    "comments": [],
                }
            ],
            "summary": "HTTP open.",
        })),
    ])
    scout_backend = FakeBackend([_end(json.dumps(scout_findings_no_id))])
    backends = iter([leader_backend, scout_backend])

    def fake_factory(provider, ollama_url=None):
        return next(backends)

    artifact = run_recon_committee(
        approval=approval,
        config=config,
        _backend_factory=fake_factory,
    )

    # The tool result returned to the leader must contain Python-assigned specialist IDs.
    registered_ids = {s.id for s in artifact.specialists}
    tool_result_str = leader_backend.recorded[0][1][0]  # first recorded tool result
    findings = json.loads(tool_result_str)
    for finding in findings:
        assert finding["specialist_id"] in registered_ids, (
            f"specialist_id {finding['specialist_id']!r} was not Python-assigned"
        )


def test_recon_artifact_is_pydantic_validated(config, approval):
    """ReconArtifact rejects a malformed observation (wrong classification value)."""
    bad_artifact = json.dumps({
        "observations": [
            {
                "specialist_id": "abc",
                "command": "nmap_scan",
                "command_output": "open",
                "classification": "INVALID_VALUE",
                "category": "network",
                "comments": [],
            }
        ],
        "summary": "Done.",
    })

    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _end(bad_artifact),
        ]),
        FakeBackend([_end(json.dumps([
            {"command": "nmap_scan", "command_output": "open", "notes": "open"},
        ]))]),
    ])

    def fake_factory(provider, ollama_url=None):
        return next(backends)

    with pytest.raises(Exception):  # pydantic ValidationError on bad classification
        run_recon_committee(approval=approval, config=config, _backend_factory=fake_factory)


def test_specialists_list_includes_leader_and_summoned(config, approval):
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _end(json.dumps({
                "observations": [],
                "summary": "Nothing found.",
            })),
        ]),
        FakeBackend([_end(json.dumps([]))]),
    ])

    def fake_factory(provider, ollama_url=None):
        return next(backends)

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=fake_factory)

    titles = [s.title for s in artifact.specialists]
    assert "Recon Leader" in titles
    assert "Network Scout" in titles
    assert len(artifact.specialists) == 2
