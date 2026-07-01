"""Tests for the Retrieval committee using FakeBackend."""

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from athena.config import load_config
from athena.committees.retrieval import run_retrieval_committee
from athena.model_backend import FakeBackend, ModelResponse, ToolCall
from athena.schemas import PlanArtifact, ReconArtifact


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
          - config: ./agents/retrieval/db_specialist.yml
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
            "command_output": '{"database": {"host": "pgdatabase", "port": 5432, "username": "db_admin", "password": "Sup3rS3cr3t!2024"}}',
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
            "description": "Download and document credentials.json",
            "rationale": "Plaintext creds at /files/credentials.json",
            "observation_ids": ["obs-001"],
        },
        {
            "id": "act00002",
            "priority": "high",
            "title": "PostgreSQL schema enumeration",
            "category": "credential_access",
            "description": "Connect to PostgreSQL and enumerate all tables",
            "rationale": "Credentials found in obs-001",
            "observation_ids": ["obs-001"],
        },
    ],
    "summary": "Credential exposure is the critical path.",
})

WEB_FINDINGS = json.dumps([
    {
        "action_id": "act00001",
        "tool": "http_get",
        "tool_input": {"url": "http://target/files/credentials.json"},
        "tool_output": "200 OK: credentials.json body with plaintext password",
        "notes": "credentials.json accessible without authentication",
    }
])

DB_FINDINGS = json.dumps([
    {
        "action_id": "act00002",
        "tool": "postgres_query",
        "tool_input": {"host": "pgdatabase", "port": 5432, "database": "sarif_prod", "username": "db_admin", "password": "Sup3rS3cr3t!2024", "query": "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"},
        "tool_output": "employees | api_keys | system_config",
        "notes": "Three tables found: employees, api_keys, system_config",
    }
])

SUMMARY_JSON = json.dumps({
    "summary": "Credentials confirmed retrievable. Database accessible with exposed creds; system_config table contains additional secrets.",
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


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool_call(name: str, inp: dict, tc_id: str) -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=inp)],
    )


def test_returns_valid_retrieval_artifact(config, recon_artifact, plan_artifact) -> None:
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc1"),
            _tool_call("summon_specialist", {"name": "db_specialist"}, "tc2"),
            _end(SUMMARY_JSON),
        ]),
        FakeBackend([_end(WEB_FINDINGS)]),
        FakeBackend([_end(DB_FINDINGS)]),
    ])

    artifact = run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert artifact.run_id == plan_artifact.run_id
    assert artifact.target == "target"
    assert artifact.plan_artifact_id == plan_artifact.artifact_id
    assert len(artifact.findings) == 2
    assert artifact.summary != ""


def test_both_artifacts_injected_into_specialist_message(config, recon_artifact, plan_artifact) -> None:
    web_backend = FakeBackend([_end(WEB_FINDINGS)])
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc1"),
            _end(SUMMARY_JSON),
        ]),
        web_backend,
    ])

    run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert "PlanArtifact" in web_backend.initial_message
    assert "ReconArtifact" in web_backend.initial_message
    assert plan_artifact.artifact_id in web_backend.initial_message
    assert recon_artifact.artifact_id in web_backend.initial_message


def test_finding_ids_assigned_by_python(config, recon_artifact, plan_artifact) -> None:
    backends = iter([
        FakeBackend([_end(SUMMARY_JSON)]),
    ])

    # Leader summons no specialists — all_findings stays empty, summary still returned
    artifact = run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )
    # No findings to check IDs on, but artifact itself must be valid
    assert artifact.findings == []


def test_finding_ids_are_python_assigned(config, recon_artifact, plan_artifact) -> None:
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc1"),
            _end(SUMMARY_JSON),
        ]),
        FakeBackend([_end(WEB_FINDINGS)]),
    ])

    artifact = run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    for finding in artifact.findings:
        assert finding.id  # non-empty
        assert len(finding.id) == 8  # new_short_id() format
        assert finding.specialist_id  # Python assigned, non-empty


def test_unknown_specialist_returns_error_not_crash(config, recon_artifact, plan_artifact) -> None:
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "unknown_agent"}, "tc1"),
            _end(SUMMARY_JSON),
        ]),
    ])

    # Should not raise — leader receives the error JSON as tool result
    artifact = run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )
    assert artifact.findings == []


def test_web_retriever_http_get_dispatched(config, recon_artifact, plan_artifact, monkeypatch) -> None:
    """http_get is called when web_retriever uses the http_get tool."""
    from athena.committees import retrieval as retrieval_mod

    mock_result = MagicMock()
    mock_result.summary = "200 OK"
    mock_result.status_code = 200
    mock_result.headers = {}
    mock_result.body = "credentials body"

    captured: list[str] = []

    def fake_http_get(url: str):
        captured.append(url)
        return mock_result

    monkeypatch.setattr(retrieval_mod, "http_get", fake_http_get)

    # Specialist backend: calls http_get then returns findings
    spec_backend = FakeBackend([
        _tool_call("http_get", {"url": "http://target/files/credentials.json"}, "tc2"),
        _end(WEB_FINDINGS),
    ])
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "web_retriever"}, "tc1"),
            _end(SUMMARY_JSON),
        ]),
        spec_backend,
    ])

    run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert "http://target/files/credentials.json" in captured


def test_db_specialist_postgres_query_dispatched(config, recon_artifact, plan_artifact, monkeypatch) -> None:
    """postgres_query is called when db_specialist uses the postgres_query tool."""
    from athena.committees import retrieval as retrieval_mod

    mock_result = MagicMock()
    mock_result.error = None
    mock_result.summary = "3 rows returned"
    mock_result.query = "SELECT table_name FROM information_schema.tables"
    mock_result.columns = ["table_name"]
    mock_result.rows = [["employees"], ["api_keys"], ["system_config"]]

    captured: list[dict] = []

    def fake_postgres_query(**kwargs):
        captured.append(kwargs)
        return mock_result

    monkeypatch.setattr(retrieval_mod, "postgres_query", fake_postgres_query)

    db_inp = {
        "host": "pgdatabase",
        "port": 5432,
        "database": "sarif_prod",
        "username": "db_admin",
        "password": "Sup3rS3cr3t!2024",
        "query": "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
    }
    spec_backend = FakeBackend([
        _tool_call("postgres_query", db_inp, "tc2"),
        _end(DB_FINDINGS),
    ])
    backends = iter([
        FakeBackend([
            _tool_call("summon_specialist", {"name": "db_specialist"}, "tc1"),
            _end(SUMMARY_JSON),
        ]),
        spec_backend,
    ])

    run_retrieval_committee(
        plan_artifact=plan_artifact,
        recon_artifact=recon_artifact,
        config=config,
        _backend_factory=lambda p, u=None: next(backends),
    )

    assert len(captured) == 1
    assert captured[0]["host"] == "pgdatabase"
