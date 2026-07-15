"""Pipeline thread management and engagement lifecycle.

One engagement at a time. The pipeline runs in a ThreadPoolExecutor so it
does not block the FastAPI event loop. EngagementContext holds all the
state needed for the server to interact with a running pipeline:

  - reply_event / pending_question / pending_answer: for the orchestrator's
    ask_user blocking mechanism (Option B from WORKSPACE_ARCH.md).
  - agent_queues: per-leader queue.Queues for mid-run operator chat.

This module is a pure service layer — no FastAPI imports.
"""

from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pubsub import pub

from athena.config import AthenaConfig
from athena.model_backend import make_backend
from athena.orchestrator import run_orchestrator
from athena.utils import new_id

_log = logging.getLogger("athena.server.runner")

# Agent IDs for committee leaders — pre-created queues so operators can
# send messages before or during a leader's run.
_LEADER_AGENT_IDS = [
    "athena.recon.leader",
    "athena.planning.leader",
    "athena.retrieval.leader",
    "athena.reporting.leader",
]

# Orchestrator's virtual agent_id for POST /chat routing.
ORCHESTRATOR_AGENT_ID = "athena.orchestrator"

# One worker: enforces the "one engagement at a time" constraint.
_executor = ThreadPoolExecutor(max_workers=1)

_active: dict[str, "EngagementContext"] = {}


@dataclass
class EngagementContext:
    run_id: str
    status: str  # "running" | "completed" | "rejected" | "failed"
    # Orchestrator ask_user gate — pipeline thread blocks here.
    reply_event: threading.Event = field(default_factory=threading.Event)
    pending_question: str | None = None
    pending_answer: str | None = None
    # Per-leader queues for mid-run operator injection.
    agent_queues: dict[str, queue.Queue] = field(default_factory=dict)


def get_context(run_id: str) -> EngagementContext | None:
    return _active.get(run_id)


def is_busy() -> bool:
    return any(ctx.status == "running" for ctx in _active.values())


def start_engagement(instructions: str, config: AthenaConfig) -> str:
    """Start a new engagement in the background. Returns the pre-generated run_id."""
    if is_busy():
        raise RuntimeError("An engagement is already in progress")

    run_id = new_id()
    ctx = EngagementContext(run_id=run_id, status="running")
    for leader_id in _LEADER_AGENT_IDS:
        ctx.agent_queues[leader_id] = queue.Queue()
    _active[run_id] = ctx

    def _ask_user_handler(question: str) -> str:
        ctx.pending_question = question
        ctx.reply_event.clear()
        pub.sendMessage("orchestrator.question", run_id=run_id, question=question)
        answered = ctx.reply_event.wait(timeout=300)
        ctx.pending_question = None
        if not answered:
            # Timed out — unblock the pipeline with a neutral response.
            return "No operator response within timeout; proceed with best judgement."
        answer = ctx.pending_answer or ""
        ctx.pending_answer = None
        return answer

    def _run() -> None:
        try:
            result = run_orchestrator(
                instructions=instructions,
                config=config,
                _backend_factory=make_backend,
                ask_user_handler=_ask_user_handler,
                run_id=run_id,
                leader_queues=ctx.agent_queues,
            )
            ctx.status = "completed" if result is not None else "rejected"
        except Exception:
            _log.exception("engagement %s failed", run_id)
            ctx.status = "failed"

    _executor.submit(_run)
    return run_id


def reply_to_orchestrator(run_id: str, answer: str) -> None:
    """Unblock the orchestrator's ask_user wait with the operator's answer."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    ctx.pending_answer = answer
    ctx.reply_event.set()
    pub.sendMessage("orchestrator.answer", run_id=run_id, answer=answer)


def send_to_agent(run_id: str, agent_id: str, message: str) -> None:
    """Put a message into a committee leader's queue for mid-run injection."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    q = ctx.agent_queues.get(agent_id)
    if q is None:
        raise KeyError(f"No queue for agent: {agent_id!r}")
    q.put_nowait(message)
