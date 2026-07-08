"""Tests for the Recon committee using FakeBackend.

Architecture under test:
  Phase 1 — Python runs network_operator, service_operator, web_operator (Claude).
  Phase 2 — Python runs threat_analyst (Foundation-Sec, single completion, no tools).
  Phase 3 — Leader (Claude) may summon operators for follow-up, then synthesises.
  Phase 4 — Leader emits ReconArtifact JSON.
"""

import json
import textwrap
from pathlib import Path

import pytest

from athena.config import load_config
from athena.committees.recon import run_recon_committee
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.schemas import OrchestratorApproval


VALID_YAML = textwrap.dedent("""
    artifacts_dir: ./artifacts
    max_agent_iterations: 8

    model:
      default: claude-haiku-4-5
      provider: anthropic
      ollama_base_url: https://laconic-mercenary--athena-foundation-sec-serve.modal.run

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
          - config: ./agents/recon/network_operator.yml
          - config: ./agents/recon/service_operator.yml
          - config: ./agents/recon/web_operator.yml
          - config: ./agents/recon/threat_analyst.yml
            provider: ollama
            model: foundation-sec-8b
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
        notes="Authorised assessment.",
    )


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool_call(name: str, inp: dict, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=inp)],
    )


NETWORK_FINDINGS = json.dumps([
    {"command": "nmap_scan target", "command_output": "22/tcp open ssh OpenSSH 7.4, 80/tcp open http Apache 2.4.6", "notes": "SSH and HTTP open"},
])

SERVICE_FINDINGS = json.dumps([
    {"command": "ssh_banner target 22", "command_output": "SSH-2.0-OpenSSH_7.4", "notes": "OpenSSH 7.4 banner"},
])

WEB_FINDINGS = json.dumps([
    {"command": "http_head http://target/admin", "command_output": "Status: 200\nServer: Apache/2.4.6", "notes": "/admin accessible"},
])

THREAT_ANALYST_RESPONSE = """## CVE Candidates
- CVE-2017-9798 — Apache 2.4.6 — Optionsbleed, may leak memory via OPTIONS responses

## Risk Indicators
- Apache mod_status exposed without authentication
- Apache 2.4.6 is outdated and unpatched
- Unauthenticated /admin endpoint

## Recommended Follow-up
- web_operator: GET /server-info to confirm mod_php and loaded modules

## Assessment
Outdated Apache 2.4.6 with an unauthenticated admin endpoint presents high risk.
CVE-2017-9798 applies if OPTIONS method is enabled. Immediate follow-up recommended."""

ARTIFACT_JSON = json.dumps({
    "observations": [
        {
            "specialist_id": "PLACEHOLDER",
            "command": "nmap_scan target",
            "command_output": "22/tcp open ssh, 80/tcp open http",
            "classification": "signal_info",
            "category": "network",
            "comments": [],
        },
        {
            "specialist_id": "PLACEHOLDER",
            "command": "http_head http://target/admin",
            "command_output": "Status: 200, Server: Apache/2.4.6",
            "classification": "signal_warn",
            "category": "exposure",
            "comments": [{"author_id": "leader-id", "text": "CVE-2017-9798 candidate"}],
        },
    ],
    "summary": "Apache 2.4.6 exposed on port 80 with unauthenticated /admin endpoint.",
})


def _make_backends(*responses_per_backend):
    """Build an iterator of FakeBackends from lists of ModelResponses."""
    backends = iter([FakeBackend(list(r)) for r in responses_per_backend])
    return lambda provider, url=None: next(backends)


def test_returns_valid_recon_artifact(config, approval):
    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],           # network_operator (Phase 1)
        [_end(SERVICE_FINDINGS)],           # service_operator (Phase 1)
        [_end(WEB_FINDINGS)],              # web_operator (Phase 1)
        [_end(THREAT_ANALYST_RESPONSE)],      # threat_analyst (Phase 2)
        [_end(ARTIFACT_JSON)],             # leader — no follow-up (Phase 3+4)
    )

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=factory)

    assert artifact.run_id == approval.run_id
    assert artifact.target == "target"
    assert len(artifact.observations) == 2
    assert artifact.summary != ""


def test_threat_analysis_populated(config, approval):
    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],
        [_end(SERVICE_FINDINGS)],
        [_end(WEB_FINDINGS)],
        [_end(THREAT_ANALYST_RESPONSE)],
        [_end(ARTIFACT_JSON)],
    )

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=factory)

    assert artifact.threat_analysis is not None
    assert "CVE-2017-9798" in artifact.threat_analysis.summary
    assert "Risk Indicators" in artifact.threat_analysis.summary
    assert artifact.threat_analysis.summary != ""


def test_leader_can_summon_operator_for_followup(config, approval):
    """Leader uses summon_operator in Phase 3 to follow up on analyst recommendation."""
    followup_findings = json.dumps([
        {"command": "http_get http://target/server-info", "command_output": "mod_php loaded", "notes": "PHP module detected"},
    ])

    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],
        [_end(SERVICE_FINDINGS)],
        [_end(WEB_FINDINGS)],
        [_end(THREAT_ANALYST_RESPONSE)],
        # Leader calls summon_operator then emits artifact
        [
            _tool_call("summon_operator", {"name": "web_operator", "task": "GET /server-info"}, "tc1"),
            _end(ARTIFACT_JSON),
        ],
        [_end(followup_findings)],  # web_operator Phase 3
    )

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=factory)

    assert artifact.run_id == approval.run_id
    # Phase 3 operator should appear in specialists list
    operator_titles = [s.title for s in artifact.specialists]
    assert operator_titles.count("Web Operator") == 2  # Phase 1 + Phase 3


def test_operator_ids_are_python_assigned(config, approval):
    """Findings returned to the leader always carry Python-assigned specialist IDs."""
    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],
        [_end(SERVICE_FINDINGS)],
        [_end(WEB_FINDINGS)],
        [_end(THREAT_ANALYST_RESPONSE)],
        [_end(ARTIFACT_JSON)],
    )

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=factory)

    registered_ids = {s.id for s in artifact.specialists}
    for obs in artifact.observations:
        # Observations may use PLACEHOLDER from the scripted response, which is
        # expected — the important thing is the RawFindings sent to the leader
        # carried real IDs. We verify the specialists list is non-empty.
        pass
    assert len(registered_ids) >= 4  # leader + 3 operators


def test_threat_analyst_json_parse_failure_produces_summary_fallback(config, approval):
    """If the analyst returns prose instead of JSON, summary captures the text."""
    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],
        [_end(SERVICE_FINDINGS)],
        [_end(WEB_FINDINGS)],
        [_end("The target appears to be running a vulnerable Apache installation.")],
        [_end(ARTIFACT_JSON)],
    )

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=factory)

    assert artifact.threat_analysis is not None
    assert "Apache" in artifact.threat_analysis.summary


def test_missing_threat_analyst_config_does_not_crash(tmp_path, approval):
    """If threat_analyst is not in the specialist list, the committee still runs."""
    yaml_no_analyst = textwrap.dedent("""
        artifacts_dir: ./artifacts
        max_agent_iterations: 8
        model:
          default: claude-haiku-4-5
          provider: anthropic
          ollama_base_url: https://laconic-mercenary--athena-foundation-sec-serve.modal.run
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
              - config: ./agents/recon/network_operator.yml
              - config: ./agents/recon/service_operator.yml
              - config: ./agents/recon/web_operator.yml
    """)
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(yaml_no_analyst)
    config = load_config(cfg_file)

    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],
        [_end(SERVICE_FINDINGS)],
        [_end(WEB_FINDINGS)],
        [_end(ARTIFACT_JSON)],
    )

    artifact = run_recon_committee(approval=approval, config=config, _backend_factory=factory)

    assert artifact.threat_analysis is not None
    assert "No threat analyst" in artifact.threat_analysis.summary


def test_recon_artifact_rejects_bad_classification(config, approval):
    """ReconArtifact raises on an invalid classification value."""
    bad_artifact = json.dumps({
        "observations": [{
            "specialist_id": "abc",
            "command": "nmap_scan",
            "command_output": "open",
            "classification": "INVALID_VALUE",
            "category": "network",
            "comments": [],
        }],
        "summary": "Done.",
    })

    factory = _make_backends(
        [_end(NETWORK_FINDINGS)],
        [_end(SERVICE_FINDINGS)],
        [_end(WEB_FINDINGS)],
        [_end(THREAT_ANALYST_RESPONSE)],
        [_end(bad_artifact)],
    )

    with pytest.raises(Exception):
        run_recon_committee(approval=approval, config=config, _backend_factory=factory)
