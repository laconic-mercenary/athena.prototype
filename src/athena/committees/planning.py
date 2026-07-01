"""Planning committee: Leader + two specialists.

The Leader receives the full ReconArtifact and coordinates two reasoning-only
specialists (no tools) to produce a prioritised PlanArtifact.

Artifact handoff: the ReconArtifact JSON is injected by Python into each
specialist's initial message. Specialists reason over it and output a JSON
array of suggested PlannedActions. The leader synthesises all suggestions
into the final PlanArtifact.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import yaml

from athena.agent_loop import run_agent
from athena.config import AthenaConfig
from athena.model_backend import BackendFactory, make_backend
from athena.schemas import PlanArtifact, PlannedAction, ReconArtifact, Specialist
from athena.utils import extract_json

_log = logging.getLogger("athena.planning")

_SUMMON_SPECIALIST = {
    "name": "summon_specialist",
    "description": (
        "Summon a planning specialist with the full ReconArtifact. "
        "Returns their suggested actions as a JSON array."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": ["network_planner", "web_planner"],
                "description": "Specialist to summon",
            },
        },
        "required": ["name"],
    },
}

from athena.model_backend import ToolDefinition

_SUMMON_TOOL = ToolDefinition(
    name=_SUMMON_SPECIALIST["name"],
    description=_SUMMON_SPECIALIST["description"],
    parameters=_SUMMON_SPECIALIST["parameters"],
)

_SPECIALIST_TITLES: dict[str, str] = {
    "network_planner": "Network Planner",
    "web_planner": "Web Planner",
}


def _load_system(config_path: Path) -> str:
    raw = yaml.safe_load(config_path.read_text())
    if "system" not in raw:
        raise ValueError(f"Agent config {config_path} missing 'system' field")
    return raw["system"]


def _resolve(local: Optional[str], committee: Optional[str], global_: str) -> str:
    return local or committee or global_


def run_planning_committee(
    recon_artifact: ReconArtifact,
    config: AthenaConfig,
    _backend_factory: BackendFactory = make_backend,
) -> PlanArtifact:
    """Run the Planning committee and return a validated PlanArtifact."""
    planning_cfg = config.committees["planning"]
    global_model = config.model.default
    global_provider = config.model.provider
    ollama_url = config.model.ollama_base_url

    spec_by_name = {
        Path(s.config_path).stem: s for s in planning_cfg.specialists
    }

    summoned: list[Specialist] = []

    # Serialise the recon artifact once; injected into every specialist's context.
    recon_json = recon_artifact.model_dump_json(indent=2)

    def _run_specialist(name: str) -> str:
        if name not in spec_by_name:
            return json.dumps({"error": f"Unknown specialist: {name!r}"})

        spec_cfg = spec_by_name[name]
        model = _resolve(spec_cfg.model, planning_cfg.model, global_model)
        provider = _resolve(spec_cfg.provider, planning_cfg.provider, global_provider)

        specialist = Specialist(title=_SPECIALIST_TITLES[name])
        summoned.append(specialist)

        _log.info("summoning %s", name)
        system = _load_system(spec_cfg.config_path)
        backend = _backend_factory(provider, ollama_url)

        # Full ReconArtifact handed off here — this is the inter-committee handoff.
        initial = (
            f"Target: {recon_artifact.target}\n"
            f"Your specialist ID: {specialist.id}\n\n"
            f"ReconArtifact:\n{recon_json}\n\n"
            "Analyse the findings relevant to your specialty. "
            "Output ONLY the JSON array of suggested actions when done."
        )

        raw = run_agent(
            agent_id=f"athena.planning.{name}",
            system=system,
            initial_message=initial,
            tools=[],
            tool_dispatch=lambda n, i: f"Unknown tool: {n!r}",
            backend=backend,
            model=model,
            max_iterations=config.max_agent_iterations,
        )

        try:
            items = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return json.dumps({"error": f"Invalid JSON from {name}: {exc}", "raw": raw[:400]})

        # Assign IDs in Python — don't trust LLM to generate them.
        actions = [
            PlannedAction(
                priority=item.get("priority", "medium"),
                title=item.get("title", ""),
                category=item.get("category", ""),
                description=item.get("description", ""),
                rationale=item.get("rationale", ""),
                observation_ids=item.get("observation_ids", []),
            )
            for item in items
        ]
        _log.info("%s complete — %d action(s) suggested", name, len(actions))
        return json.dumps([a.model_dump() for a in actions])

    # --- Leader ---
    leader_cfg = planning_cfg.leader
    leader_model = _resolve(leader_cfg.model, planning_cfg.model, global_model)
    leader_provider = _resolve(leader_cfg.provider, planning_cfg.provider, global_provider)

    leader = Specialist(title="Planning Leader")
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
        "Begin the planning committee workflow."
    )

    _log.info("leader synthesising plan")
    raw_plan = run_agent(
        agent_id="athena.planning.leader",
        system=leader_system,
        initial_message=leader_initial,
        tools=[_SUMMON_TOOL],
        tool_dispatch=leader_dispatch,
        backend=leader_backend,
        model=leader_model,
        max_iterations=config.max_agent_iterations,
        max_tokens=8192,
    )

    plan_data = extract_json(raw_plan)

    actions = [
        PlannedAction(
            priority=a.get("priority", "medium"),
            title=a.get("title", ""),
            category=a.get("category", ""),
            description=a.get("description", ""),
            rationale=a.get("rationale", ""),
            observation_ids=a.get("observation_ids", []),
        )
        for a in plan_data["actions"]
    ]

    return PlanArtifact(
        run_id=recon_artifact.run_id,
        target=recon_artifact.target,
        recon_artifact_id=recon_artifact.artifact_id,
        actions=actions,
        summary=plan_data["summary"],
    )
