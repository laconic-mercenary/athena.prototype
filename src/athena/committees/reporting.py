"""Reporting committee: Leader + two reasoning-only specialists.

The Leader receives all three upstream artifacts (Recon, Plan, Retrieval)
and coordinates two pure-reasoning specialists to produce the final
engagement report.

Specialists have no tools — they reason over the injected artifacts and
output a JSON section object. The leader synthesizes them into the final
ReportArtifact JSON.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import yaml

from athena.agent_loop import run_agent
from athena.config import AthenaConfig
from athena.model_backend import BackendFactory, ToolDefinition, make_backend
from athena.schemas import (
    PlanArtifact,
    ReconArtifact,
    ReportArtifact,
    ReportSection,
    RetrievalArtifact,
    Specialist,
)
from athena.utils import extract_json

_log = logging.getLogger("athena.reporting")

_SUMMON_SPECIALIST = ToolDefinition(
    name="summon_specialist",
    description=(
        "Summon a reporting specialist with all upstream artifacts. "
        "Returns their section as a JSON object."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": ["findings_analyst", "risk_assessor"],
                "description": "Specialist to summon",
            },
        },
        "required": ["name"],
    },
)

_SPECIALIST_TITLES: dict[str, str] = {
    "findings_analyst": "Findings Analyst",
    "risk_assessor":    "Risk Assessor",
}


def _load_system(config_path: Path) -> str:
    raw = yaml.safe_load(config_path.read_text())
    if "system" not in raw:
        raise ValueError(f"Agent config {config_path} missing 'system' field")
    return raw["system"]


def _resolve(local: Optional[str], committee: Optional[str], global_: str) -> str:
    return local or committee or global_


def run_reporting_committee(
    recon_artifact: ReconArtifact,
    plan_artifact: PlanArtifact,
    retrieval_artifact: RetrievalArtifact,
    config: AthenaConfig,
    _backend_factory: BackendFactory = make_backend,
) -> ReportArtifact:
    """Run the Reporting committee and return a validated ReportArtifact."""
    reporting_cfg = config.committees["reporting"]
    global_model = config.model.default
    global_provider = config.model.provider
    ollama_url = config.model.ollama_base_url

    spec_by_name = {
        Path(s.config_path).stem: s for s in reporting_cfg.specialists
    }

    # Serialise all three upstream artifacts once.
    recon_json = recon_artifact.model_dump_json(indent=2)
    plan_json = plan_artifact.model_dump_json(indent=2)
    retrieval_json = retrieval_artifact.model_dump_json(indent=2)

    def _run_specialist(name: str) -> str:
        if name not in spec_by_name:
            return json.dumps({"error": f"Unknown specialist: {name!r}"})

        spec_cfg = spec_by_name[name]
        model = _resolve(spec_cfg.model, reporting_cfg.model, global_model)
        provider = _resolve(spec_cfg.provider, reporting_cfg.provider, global_provider)

        specialist = Specialist(title=_SPECIALIST_TITLES[name])

        _log.info("summoning %s", name)
        system = _load_system(spec_cfg.config_path)
        backend = _backend_factory(provider, ollama_url)

        initial = (
            f"Target: {recon_artifact.target}\n"
            f"Your specialist ID: {specialist.id}\n\n"
            f"ReconArtifact:\n{recon_json}\n\n"
            f"PlanArtifact:\n{plan_json}\n\n"
            f"RetrievalArtifact:\n{retrieval_json}\n\n"
            "Analyse the artifacts relevant to your role. "
            "Output ONLY the JSON object when done."
        )

        raw = run_agent(
            agent_id=f"athena.reporting.{name}",
            system=system,
            initial_message=initial,
            tools=[],
            tool_dispatch=lambda n, i: f"Unknown tool: {n!r}",
            backend=backend,
            model=model,
            max_iterations=config.max_agent_iterations,
            max_tokens=8192,
        )

        try:
            return raw if extract_json(raw) else json.dumps({"error": "empty response"})
        except (ValueError, json.JSONDecodeError):
            return json.dumps({"error": f"Invalid JSON from {name}", "raw": raw[:400]})

    # --- Leader ---
    leader_cfg = reporting_cfg.leader
    leader_model = _resolve(leader_cfg.model, reporting_cfg.model, global_model)
    leader_provider = _resolve(leader_cfg.provider, reporting_cfg.provider, global_provider)

    leader = Specialist(title="Reporting Leader")
    leader_system = _load_system(leader_cfg.config_path)
    leader_backend = _backend_factory(leader_provider, ollama_url)

    def leader_dispatch(tool: str, inp: dict) -> str:
        if tool == "summon_specialist":
            return _run_specialist(inp["name"])
        return f"Unknown tool: {tool!r}"

    leader_initial = (
        f"Target: {recon_artifact.target}\n"
        f"Your specialist ID: {leader.id}\n\n"
        f"ReconArtifact:\n{recon_json}\n\n"
        f"PlanArtifact:\n{plan_json}\n\n"
        f"RetrievalArtifact:\n{retrieval_json}\n\n"
        "Begin the reporting committee workflow."
    )

    _log.info("leader producing report")
    raw_report = run_agent(
        agent_id="athena.reporting.leader",
        system=leader_system,
        initial_message=leader_initial,
        tools=[_SUMMON_SPECIALIST],
        tool_dispatch=leader_dispatch,
        backend=leader_backend,
        model=leader_model,
        max_iterations=config.max_agent_iterations,
        max_tokens=8192,
    )

    report_data = extract_json(raw_report)

    return ReportArtifact(
        run_id=recon_artifact.run_id,
        target=recon_artifact.target,
        retrieval_artifact_id=retrieval_artifact.artifact_id,
        executive_summary=report_data["executive_summary"],
        risk_rating=report_data["risk_rating"],
        sections=[ReportSection(**s) for s in report_data["sections"]],
        recommendations=report_data["recommendations"],
    )
