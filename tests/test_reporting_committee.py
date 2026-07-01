"""Tests for the Reporting committee using FakeBackend."""

import json
import textwrap
from pathlib import Path

import pytest

from athena.config import load_config
from athena.committees.reporting import run_reporting_committee
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.schemas import PlanArtifact, ReconArtifact, RetrievalArtifact, RiskRating


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

      planning:
        model: claude-haiku-4-5
        leader:
          config: ./agents/planning/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/planning/network_planner.yml

      retrieval:
        model: claude-haiku-4-5
        leader:
          config: ./agents/retrieval/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/retrieval/web_retriever.yml

      reporting:
        model: claude-haiku-4-5
        leader:
          config: ./agents/reporting/leader.yml
          model: claude-sonnet-4-6
        specialists:
          - config: ./agents/reporting/findings_analyst.yml
          - config: ./agents/reporting/risk_assessor.yml
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
            "command": "http_get http://target/files/credentials.json",
            "command_output": '{"database": {"host": "pgdatabase", "username": "db_admin"}}',
            "classification": "signal_warn",
            "category": "exposure",
            "comments": [],
        }
    ],
    "summary": "Credentials exposed at /files/credentials.json.",
})

PLAN_ARTIFACT_JSON = json.dumps({
    "artifact_id": "plan-art-001",
    "run_id": "run-001",
    "committee": "planning",
    "created_at": "2026-07-01T00:00:00Z",
    "target": "target",
    "recon_artifact_id": "recon-art-001",
    "actions": [
        {
            "id": "act00001",
            "priority": "critical",
            "title": "credentials.json retrieval",
            "category": "exposure",
            "description": "Download credentials.json",
            "rationale": "Plaintext creds exposed",
            "observation_ids": ["obs-001"],
        }
    ],
    "summary": "Credential exposure is the critical path.",
})

RETRIEVAL_ARTIFACT_JSON = json.dumps({
    "artifact_id": "retrieval-art-001",
    "run_id": "run-001",
    "committee": "retrieval",
    "created_at": "2026-07-01T00:00:00Z",
    "target": "target",
    "plan_artifact_id": "plan-art-001",
    "findings": [
        {
            "id": "find-001",
            "specialist_id": "spec-002",
            "action_id": "act00001",
            "tool": "http_get",
            "tool_input": {"url": "http://target/files/credentials.json"},
            "tool_output": "200 OK: plaintext credentials",
            "notes": "credentials.json readable without authentication",
        }
    ],
    "summary": "Credentials confirmed retrievable.",
})

FINDINGS_SECTION_JSON = json.dumps({
    "title": "Technical Findings",
    "content": "A credentials.json file was accessible without authentication at /files/credentials.json, exposing database credentials in plaintext.",
})

RISK_SECTION_JSON = json.dumps({
    "title": "Risk Assessment",
    "content": "Critical risk: plaintext database credentials are publicly accessible, enabling direct database compromise.",
    "risk_rating": "critical",
    "recommendations": [
        "Remove credentials.json from the web root immediately.",
        "Rotate all exposed database credentials.",
        "Disable Apache Autoindex on the /files/ directory.",
    ],
})

REPORT_ARTIFACT_JSON = json.dumps({
    "executive_summary": "A critical credential exposure was identified. Production database credentials are publicly accessible via the web server, posing an immediate risk of full database compromise.",
    "risk_rating": "critical",
    "sections": [
        {"title": "Technical Findings", "content": "credentials.json exposed plaintext database credentials."},
        {"title": "Risk Assessment", "content": "Critical risk: direct database access possible."},
    ],
    "recommendations": [
        "Remove credentials.json from the web root immediately.",
        "Rotate all exposed database credentials.",
        "Disable Apache Autoindex on the /files/ directory.",
    ],
})


@pytest.fixture
def config(tmp_path: Path):
    cfg_file = tmp_path / "athena.yml"
    cfg_file.write_text(VALID_YAML)
    return load_config(cfg_file)


@pytest.fixture
def recon_artifact():
    return ReconArtifact.model_validate_json(RECON_ARTIFACT_JSON)


@pytest.fixture
def plan_artifact():
    return PlanArtifact.model_validate_json(PLAN_ARTIFACT_JSON)


@pytest.fixture
def retrieval_artifact():
    return RetrievalArtifact.model_validate_json(RETRIEVAL_ARTIFACT_JSON)


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool_call(name: str, inp: dict, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=inp)],
    )


def test_returns_valid_report_artifact(config, recon_artifact, plan_artifact, retrieval_artifact) -> None:
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "findings_analyst"}, "tc1"),
            _tool_call("summon_specialist", {"name": "risk_assessor"}, "tc2"),
            _end(REPORT_ARTIFACT_JSON),
        ]),
        FakeBackend([_end(FINDINGS_SECTION_JSON)]),
        FakeBackend([_end(RISK_SECTION_JSON)]),
    ])

    artifact = run_reporting_committee(
        recon_artifact=recon_artifact,
        plan_artifact=plan_artifact,
        retrieval_artifact=retrieval_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert artifact.run_id == "run-001"
    assert artifact.target == "target"
    assert artifact.retrieval_artifact_id == retrieval_artifact.artifact_id
    assert artifact.risk_rating == RiskRating.critical
    assert len(artifact.sections) == 2
    assert len(artifact.recommendations) >= 1
    assert artifact.executive_summary != ""


def test_all_artifacts_injected_into_specialist_message(config, recon_artifact, plan_artifact, retrieval_artifact) -> None:
    analyst_backend = FakeBackend([_end(FINDINGS_SECTION_JSON)])
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "findings_analyst"}, "tc1"),
            _end(REPORT_ARTIFACT_JSON),
        ]),
        analyst_backend,
    ])

    run_reporting_committee(
        recon_artifact=recon_artifact,
        plan_artifact=plan_artifact,
        retrieval_artifact=retrieval_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    msg = analyst_backend.initial_message
    assert "ReconArtifact" in msg
    assert "PlanArtifact" in msg
    assert "RetrievalArtifact" in msg
    assert recon_artifact.artifact_id in msg
    assert retrieval_artifact.artifact_id in msg


def test_risk_rating_validated_by_pydantic(config, recon_artifact, plan_artifact, retrieval_artifact) -> None:
    bad_report = json.dumps({
        "executive_summary": "summary",
        "risk_rating": "EXTREME",
        "sections": [],
        "recommendations": [],
    })
    backends = iter([FakeBackend([_end(bad_report)])])

    with pytest.raises(Exception):
        run_reporting_committee(
            recon_artifact=recon_artifact,
            plan_artifact=plan_artifact,
            retrieval_artifact=retrieval_artifact,
            config=config,
            _backend_factory=lambda p, u=None: next(backends),
        )


def test_no_specialist_summoned_still_produces_artifact(config, recon_artifact, plan_artifact, retrieval_artifact) -> None:
    backends = iter([FakeBackend([_end(REPORT_ARTIFACT_JSON)])])

    artifact = run_reporting_committee(
        recon_artifact=recon_artifact,
        plan_artifact=plan_artifact,
        retrieval_artifact=retrieval_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert artifact.risk_rating == RiskRating.critical


def test_report_artifact_links_to_retrieval(config, recon_artifact, plan_artifact, retrieval_artifact) -> None:
    backends = iter([FakeBackend([_end(REPORT_ARTIFACT_JSON)])])

    artifact = run_reporting_committee(
        recon_artifact=recon_artifact,
        plan_artifact=plan_artifact,
        retrieval_artifact=retrieval_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert artifact.retrieval_artifact_id == retrieval_artifact.artifact_id
