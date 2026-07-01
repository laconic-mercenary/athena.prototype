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

def _full_pipeline_backends(extra_recon_backends=()):
    """Return a backend factory for a full orchestrator run."""
    it = iter([
        FakeBackend([_end(APPROVAL_JSON)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc1"),
            _end(RECON_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(SCOUT_FINDINGS)]),
        *extra_recon_backends,
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_planner"}, "tc2"),
            _end(PLAN_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(NETWORK_PLAN_ACTIONS)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc3"),
            _end(RETRIEVAL_SUMMARY_JSON),
        ]),
        FakeBackend([_end(WEB_FINDINGS)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "findings_analyst"}, "tc4"),
            _tool_call("summon_specialist", {"name": "risk_assessor"}, "tc5"),
            _end(REPORT_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(FINDINGS_SECTION_JSON)]),
        FakeBackend([_end(RISK_SECTION_JSON)]),
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
        ]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_scout"}, "tc2"),
            _end(RECON_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(SCOUT_FINDINGS)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "network_planner"}, "tc3"),
            _end(PLAN_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(NETWORK_PLAN_ACTIONS)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc4"),
            _end(RETRIEVAL_SUMMARY_JSON),
        ]),
        FakeBackend([_end(WEB_FINDINGS)]),
        FakeBackend([
            _tool_call("summon_specialist", {"name": "findings_analyst"}, "tc5"),
            _tool_call("summon_specialist", {"name": "risk_assessor"}, "tc6"),
            _end(REPORT_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(FINDINGS_SECTION_JSON)]),
        FakeBackend([_end(RISK_SECTION_JSON)]),
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
