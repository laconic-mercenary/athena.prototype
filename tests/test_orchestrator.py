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

      planning:
        model: claude-haiku-4-5
        leader:
          config: ./agents/planning/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/planning/network_planner.yml
          - config: ./agents/planning/web_planner.yml

      retrieval:
        model: claude-haiku-4-5
        leader:
          config: ./agents/retrieval/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/retrieval/web_retriever.yml
          - config: ./agents/retrieval/db_specialist.yml

      reporting:
        model: claude-haiku-4-5
        leader:
          config: ./agents/reporting/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/reporting/findings_analyst.yml
          - config: ./agents/reporting/risk_assessor.yml
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

# Recon leader now emits one record_observation tool call per finding, then
# outputs only {"summary": "..."} as its final text response.
RECON_OBS_DATA = {
    "specialist_id": "abc",
    "command": "nmap_scan",
    "command_output": "80/tcp open",
    "classification": "signal_info",
    "category": "network",
    "comments": [],
}
RECON_SUMMARY_JSON = json.dumps({"summary": "HTTP open on port 80."})

NETWORK_OP_FINDINGS = json.dumps([
    {"command": "nmap_scan target", "command_output": "80/tcp open http", "notes": "HTTP open"},
])

SERVICE_OP_FINDINGS = json.dumps([
    {"command": "ssh_banner target 80", "command_output": "Apache/2.4.6", "notes": "Apache banner"},
])

WEB_OP_FINDINGS = json.dumps([
    {"command": "http_head http://target/admin", "command_output": "Status: 200", "notes": "/admin accessible"},
])

THREAT_ANALYST_RESPONSE = """## CVE Candidates
- CVE-2017-9798 — Apache 2.4.6 — Optionsbleed

## Risk Indicators
- Unauthenticated /admin endpoint

## Recommended Follow-up
- (none)

## Assessment
Outdated Apache with exposed admin endpoint."""

NETWORK_PLAN_ACTIONS = json.dumps([
    {"priority": "high", "title": "SSH credential reuse test", "category": "credential_access", "description": "Test SSH", "rationale": "Port open", "observation_ids": []},
])

PLAN_ARTIFACT_JSON = json.dumps({
    "actions": [
        {"priority": "high", "title": "SSH credential reuse test", "category": "credential_access", "description": "Test SSH", "rationale": "Port open", "observation_ids": []},
    ],
    "summary": "Probe SSH with discovered credentials.",
})

WEB_FINDINGS = json.dumps([
    {
        "action_id": "act00001",
        "tool": "http_get",
        "tool_input": {"url": "http://target/files/credentials.json"},
        "tool_output": "200 OK: credentials found",
        "notes": "credentials.json accessible without authentication",
    }
])

RETRIEVAL_SUMMARY_JSON = json.dumps({
    "summary": "Credentials retrieved. Database enumerated.",
})

FINDINGS_SECTION_JSON = json.dumps({
    "title": "Technical Findings",
    "content": "Credentials.json exposed plaintext database credentials.",
})

RISK_SECTION_JSON = json.dumps({
    "title": "Risk Assessment",
    "content": "Critical: direct database access possible.",
    "risk_rating": "critical",
    "recommendations": ["Remove credentials.json from web root."],
})

REPORT_ARTIFACT_JSON = json.dumps({
    "executive_summary": "Critical credential exposure. Immediate remediation required.",
    "risk_rating": "critical",
    "sections": [
        {"title": "Technical Findings", "content": "Credentials exposed."},
        {"title": "Risk Assessment", "content": "Critical risk."},
    ],
    "recommendations": ["Remove credentials.json from web root.", "Rotate credentials."],
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _full_pipeline_backends():
    """Return a backend factory for a full orchestrator run."""
    it = iter([
        FakeBackend([_end(APPROVAL_JSON)]),                      # orchestrator
        FakeBackend([_end(NETWORK_OP_FINDINGS)]),                 # recon Phase 1: network_operator
        FakeBackend([_end(SERVICE_OP_FINDINGS)]),                 # recon Phase 1: service_operator
        FakeBackend([_end(WEB_OP_FINDINGS)]),                    # recon Phase 1: web_operator
        FakeBackend([_end(THREAT_ANALYST_RESPONSE)]),               # recon Phase 2: threat_analyst
        FakeBackend([                                            # recon Phase 3+4: leader
            _tool_call("record_observation", RECON_OBS_DATA, "tc-recon-obs"),
            _end(RECON_SUMMARY_JSON),
        ]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_planner"}, "tc1"),
            _end(PLAN_ARTIFACT_JSON),
        ]),                                                       # planning leader
        FakeBackend([_end(NETWORK_PLAN_ACTIONS)]),               # network_planner
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc2"),
            _end(RETRIEVAL_SUMMARY_JSON),
        ]),                                                       # retrieval leader
        FakeBackend([_end(WEB_FINDINGS)]),                       # web_retriever
        FakeBackend([
            _tool_call("summon_specialist", {"name": "findings_analyst"}, "tc3"),
            _tool_call("summon_specialist", {"name": "risk_assessor"}, "tc4"),
            _end(REPORT_ARTIFACT_JSON),
        ]),                                                       # reporting leader
        FakeBackend([_end(FINDINGS_SECTION_JSON)]),              # findings_analyst
        FakeBackend([_end(RISK_SECTION_JSON)]),                  # risk_assessor
    ])
    return lambda p, u=None: next(it)


def test_approval_path_returns_approval(config) -> None:
    result = run_orchestrator(
        instructions="Probe the target container.",
        config=config,
        _backend_factory=_full_pipeline_backends(),
    )

    assert result is not None
    assert result.target == "target"
    assert result.notes == "Local authorized probe."


def test_approval_path_writes_artifacts(config, tmp_path) -> None:
    result = run_orchestrator(
        instructions="Probe the target.",
        config=config,
        _backend_factory=_full_pipeline_backends(),
    )

    assert result is not None
    run_dir = config.artifacts_dir / result.run_id
    assert (run_dir / "run.log").exists()
    assert (run_dir / "approval.json").exists()
    assert (run_dir / "recon.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "retrieval.json").exists()
    assert (run_dir / "report.json").exists()

    log_text = (run_dir / "run.log").read_text()
    for event in [
        "run started",
        "recon committee summoned", "recon artifact emitted",
        "planning committee summoned", "plan artifact emitted",
        "retrieval committee summoned", "retrieval artifact emitted",
        "reporting committee summoned", "report artifact emitted",
        "run completed",
    ]:
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
    """Orchestrator asks a question, gets an answer, then runs the full pipeline."""
    monkeypatch.setattr("builtins.input", lambda _: "target")

    backends = iter([
        FakeBackend([
            _tool_call("ask_user", {"question": "What is the target hostname?"}, "tc1"),
            _end(APPROVAL_JSON),
        ]),                                                               # orchestrator
        FakeBackend([_end(NETWORK_OP_FINDINGS)]),                         # recon Phase 1: network_operator
        FakeBackend([_end(SERVICE_OP_FINDINGS)]),                         # recon Phase 1: service_operator
        FakeBackend([_end(WEB_OP_FINDINGS)]),                            # recon Phase 1: web_operator
        FakeBackend([_end(THREAT_ANALYST_RESPONSE)]),                       # recon Phase 2: threat_analyst
        FakeBackend([                                                     # recon Phase 3+4: leader
            _tool_call("record_observation", RECON_OBS_DATA, "tc-recon-obs"),
            _end(RECON_SUMMARY_JSON),
        ]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_planner"}, "tc2"),
            _end(PLAN_ARTIFACT_JSON),
        ]),                                                               # planning leader
        FakeBackend([_end(NETWORK_PLAN_ACTIONS)]),                       # network_planner
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc3"),
            _end(RETRIEVAL_SUMMARY_JSON),
        ]),                                                               # retrieval leader
        FakeBackend([_end(WEB_FINDINGS)]),                               # web_retriever
        FakeBackend([
            _tool_call("summon_specialist", {"name": "findings_analyst"}, "tc4"),
            _tool_call("summon_specialist", {"name": "risk_assessor"}, "tc5"),
            _end(REPORT_ARTIFACT_JSON),
        ]),                                                               # reporting leader
        FakeBackend([_end(FINDINGS_SECTION_JSON)]),                      # findings_analyst
        FakeBackend([_end(RISK_SECTION_JSON)]),                          # risk_assessor
    ])

    result = run_orchestrator(
        instructions="Probe something.",
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert result is not None
    assert result.target == "target"


def test_artifacts_are_valid_pydantic(config, tmp_path) -> None:
    """recon.json, plan.json, and retrieval.json all round-trip through Pydantic."""
    from athena.schemas import PlanArtifact, ReconArtifact, RetrievalArtifact

    result = run_orchestrator(
        instructions="Probe the target.",
        config=config,
        _backend_factory=_full_pipeline_backends(),
    )

    assert result is not None
    run_dir = config.artifacts_dir / result.run_id

    recon = ReconArtifact.model_validate_json((run_dir / "recon.json").read_text())
    assert recon.target == "target"
    assert len(recon.observations) == 1

    plan = PlanArtifact.model_validate_json((run_dir / "plan.json").read_text())
    assert plan.target == "target"
    assert plan.recon_artifact_id == recon.artifact_id
    assert len(plan.actions) >= 1

    retrieval = RetrievalArtifact.model_validate_json((run_dir / "retrieval.json").read_text())
    assert retrieval.target == "target"
    assert retrieval.plan_artifact_id == plan.artifact_id

    from athena.schemas import ReportArtifact
    report = ReportArtifact.model_validate_json((run_dir / "report.json").read_text())
    assert report.target == "target"
    assert report.retrieval_artifact_id == retrieval.artifact_id
