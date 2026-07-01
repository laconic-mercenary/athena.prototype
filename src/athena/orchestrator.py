"""Orchestrator: two-phase pipeline entry point.

Phase 1 — Clarification loop (interactive):
  The Orchestrator LLM reads the instructions, may ask the user questions
  via ask_user, or reject the run via reject_run. When satisfied it emits
  an OrchestratorApproval JSON and stops.

Phase 2 — Pipeline execution (deterministic):
  Python takes the approval and drives the committee sequence. No LLM
  decisions happen here — the order is fixed in code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

from athena.agent_loop import run_agent
from athena.artifacts import RunLogger
from athena.committees.recon import run_recon_committee
from athena.config import AthenaConfig
from athena.model_backend import BackendFactory, ModelBackend, ToolDefinition, make_backend
from athena.schemas import OrchestratorApproval
from athena.utils import extract_json

_log = logging.getLogger("athena.orchestrator")

_ASK_USER = ToolDefinition(
    name="ask_user",
    description="Ask the user a clarifying question and wait for their answer.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Question to ask the user"},
        },
        "required": ["question"],
    },
)

_REJECT_RUN = ToolDefinition(
    name="reject_run",
    description=(
        "Refuse the engagement and exit cleanly. Use when instructions are out of scope, "
        "request offensive actions, or cannot be made safe."
    ),
    parameters={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Clear explanation of the rejection"},
        },
        "required": ["reason"],
    },
)


class RunRejected(Exception):
    """Raised inside the dispatch function when the Orchestrator calls reject_run."""
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _load_system(config_path: Path) -> str:
    raw = yaml.safe_load(config_path.read_text())
    if "system" not in raw:
        raise ValueError(f"Agent config {config_path} missing 'system' field")
    return raw["system"]


def run_orchestrator(
    instructions: str,
    config: AthenaConfig,
    _backend_factory: BackendFactory = make_backend,
) -> OrchestratorApproval | None:
    """Run the full two-phase pipeline.

    Returns the OrchestratorApproval if the run completed, None if rejected.
    """
    orch_cfg = config.orchestrator
    provider = orch_cfg.provider or config.model.provider
    system = _load_system(orch_cfg.config_path)

    interactive = sys.stdin.isatty()

    def dispatch(tool: str, inp: dict) -> str:
        if tool == "ask_user":
            print(f"\n[Orchestrator] {inp['question']}")
            return input("> ").strip()
        if tool == "reject_run":
            raise RunRejected(inp["reason"])
        return f"Unknown tool: {tool!r}"

    # ask_user is only available when running interactively — omit it in Docker/CI
    # so the model is forced to approve or reject based on the instructions alone.
    tools = [_ASK_USER, _REJECT_RUN] if interactive else [_REJECT_RUN]

    # --- Phase 1: clarification loop ---
    _log.info("reading instructions...")
    try:
        approval_json = run_agent(
            agent_id="athena.orchestrator",
            system=system,
            initial_message=instructions,
            tools=tools,
            tool_dispatch=dispatch,
            backend=_backend_factory(provider, config.model.ollama_base_url),
            model=orch_cfg.model,
            max_iterations=config.max_agent_iterations,
        )
    except RunRejected as exc:
        _log.info("run rejected: %s", exc.reason)
        return None

    data = extract_json(approval_json)
    approval = OrchestratorApproval(target=data["target"], notes=data["notes"])
    _log.info("approved — target: %s", approval.target)
    _log.info(approval.notes)

    # --- Phase 2: deterministic pipeline ---
    logger = RunLogger(approval.run_id, config.artifacts_dir)
    logger.log("run started")
    logger.write_artifact("approval", approval.model_dump_json(indent=2))

    logger.log("recon committee summoned")
    logger.log("recon committee working")

    recon_artifact = run_recon_committee(
        approval=approval,
        config=config,
        _backend_factory=_backend_factory,
    )

    logger.log("recon artifact emitted")
    logger.write_artifact("recon", recon_artifact.model_dump_json(indent=2))
    logger.log("recon committee spun down")
    logger.log("run completed")

    return approval
