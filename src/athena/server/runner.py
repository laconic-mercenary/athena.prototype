"""Pipeline thread management and engagement lifecycle — ensemble harness edition.

One engagement at a time. The pipeline runs in a ThreadPoolExecutor so it
does not block the FastAPI event loop. EngagementContext holds all state
the server needs to interact with a running pipeline.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pubsub import pub

from athena.ensemble.loader import load_ensemble
from athena.ensemble.types import LoadedEnsemble
from athena.harness.orchestrator import OrchestratorHarness
from athena.harness.workflow import GLOBAL_STEP_BUDGET, run_workflow
from athena.model_backend import make_backend
from athena.utils import new_id

_log = logging.getLogger("athena.server.runner")

ORCHESTRATOR_MODEL = os.environ.get("ORCHESTRATOR_MODEL", "claude-sonnet-4-6")
ORCHESTRATOR_AGENT_ID = "athena.orchestrator"

_executor = ThreadPoolExecutor(max_workers=1)
_active: dict[str, "EngagementContext"] = {}


@dataclass
class EngagementContext:
    run_id: str
    status: str   # "running" | "completed" | "rejected" | "failed"

    reply_event: threading.Event
    plan_decision_event: threading.Event
    awaiting_approval: bool
    leader_queues: dict[str, queue.Queue]
    # Optional state (None-defaulted fields must follow required fields)
    # Set once the orchestrator loop thread starts (after plan approval).
    orchestrator: OrchestratorHarness | None = None
    pending_question: str | None = None
    pending_answer: str | None = None
    plan_decision_type: str | None = None
    revision_message: str | None = None


def get_context(run_id: str) -> EngagementContext | None:
    return _active.get(run_id)


def is_busy() -> bool:
    return any(ctx.status == "running" for ctx in _active.values())


def _resolve_ensemble_path() -> Path:
    env = os.environ.get("ENSEMBLE_PATH")
    if env:
        return Path(env)
    raise RuntimeError(
        "No ensemble configured. Set the ENSEMBLE_PATH environment variable."
    )


def start_engagement(instructions: str) -> str:
    """Start a new engagement. Returns the pre-generated run_id."""
    if is_busy():
        raise RuntimeError("An engagement is already in progress")

    ensemble_path = _resolve_ensemble_path()
    ensemble = load_ensemble(ensemble_path)

    run_id = new_id()
    ctx = EngagementContext(
        run_id=run_id,
        status="running",
        reply_event=threading.Event(),
        plan_decision_event=threading.Event(),
        awaiting_approval=False,
        leader_queues={},
    )
    _active[run_id] = ctx

    def _ask_user_handler(question: str) -> str:
        ctx.pending_question = question
        ctx.reply_event.clear()
        pub.sendMessage("orchestrator.question", run_id=run_id, question=question)
        answered = ctx.reply_event.wait(timeout=300)
        ctx.pending_question = None
        if not answered:
            return "No operator response within timeout; proceed with best judgement."
        answer = ctx.pending_answer or ""
        ctx.pending_answer = None
        return answer

    def _approval_handler() -> bool:
        # workflow.py already publishes gate.awaiting_approval with the correct
        # committee name before calling this function — don't duplicate it here.
        ctx.awaiting_approval = True
        ctx.plan_decision_type = None
        ctx.plan_decision_event.clear()
        ctx.plan_decision_event.wait()
        ctx.awaiting_approval = False
        return ctx.plan_decision_type == "approve"

    def _read_artifact_fn(name: str) -> str:
        artifacts_dir = Path("artifacts") / run_id
        path = artifacts_dir / f"{name}.json"
        if not path.exists():
            return f"No artifact found for '{name}'"
        return path.read_text()

    def _run() -> None:
        try:
            pub.sendMessage(
                "engagement.started",
                run_id=run_id,
                ensemble=ensemble.name,
                version=ensemble.version,
            )

            orch_backend = make_backend("anthropic", None)
            orchestrator = OrchestratorHarness(
                backend=orch_backend,
                model=ORCHESTRATOR_MODEL,
                run_id=run_id,
                ask_user_handler=_ask_user_handler,
                read_artifact_fn=_read_artifact_fn,
            )

            orchestrator.start_briefing(
                ensemble_name=ensemble.name,
                version=ensemble.version,
                capability=ensemble.capability,
                operator_message=instructions,
            )

            # Briefing + revision loop: operator may request changes before approving.
            while True:
                plan = orchestrator.run_briefing()

                for committee_name in ensemble.committees:
                    ctx.leader_queues.setdefault(committee_name, queue.Queue())

                ctx.awaiting_approval = True
                ctx.plan_decision_type = None
                ctx.revision_message = None
                ctx.plan_decision_event.clear()
                ctx.plan_decision_event.wait()
                ctx.awaiting_approval = False

                if ctx.plan_decision_type == "revise":
                    orchestrator.inject_revision(ctx.revision_message or "Please revise.")
                    pub.sendMessage("engagement.plan_revision", run_id=run_id)
                    continue

                if ctx.plan_decision_type != "approve":
                    pub.sendMessage(
                        "engagement.rejected", run_id=run_id, reason="Operator rejected the plan"
                    )
                    ctx.status = "rejected"
                    return

                break

            pub.sendMessage("engagement.approved", run_id=run_id)

            ctx.orchestrator = orchestrator
            orch_thread = threading.Thread(
                target=orchestrator.run_loop,
                name=f"orch-{run_id}",
                daemon=True,
            )
            orch_thread.start()

            try:
                run_workflow(
                    ensemble=ensemble,
                    plan=plan,
                    orchestrator=orchestrator,
                    make_backend=make_backend,
                    artifacts_dir=Path("artifacts") / run_id,
                    run_id=run_id,
                    ask_operator_handler=_ask_user_handler,
                    approval_handler=_approval_handler,
                    leader_queues=ctx.leader_queues,
                    global_step_budget=GLOBAL_STEP_BUDGET,
                )
            finally:
                orchestrator.stop()
                orch_thread.join(timeout=30)

            ctx.status = "completed"

        except Exception:
            _log.exception("engagement %s failed", run_id)
            pub.sendMessage("engagement.rejected", run_id=run_id, reason="Internal error")
            ctx.status = "failed"

    _executor.submit(_run)
    return run_id


# ---------------------------------------------------------------------------
# Server → pipeline interaction
# ---------------------------------------------------------------------------

def reply_to_orchestrator(run_id: str, answer: str) -> None:
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    ctx.pending_answer = answer
    ctx.reply_event.set()
    pub.sendMessage("orchestrator.answer", run_id=run_id, answer=answer)


def resolve_approval(run_id: str, *, approved: bool) -> None:
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    ctx.plan_decision_type = "approve" if approved else "reject"
    ctx.plan_decision_event.set()


def request_revision(run_id: str, message: str) -> None:
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    ctx.revision_message = message
    ctx.plan_decision_type = "revise"
    ctx.plan_decision_event.set()


def send_to_leader(run_id: str, committee_name: str, message: str) -> None:
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    q = ctx.leader_queues.get(committee_name)
    if q is None:
        raise KeyError(f"No leader queue for committee: {committee_name!r}")
    q.put_nowait(message)


def send_to_orchestrator(run_id: str, message: str) -> None:
    """Inject an operator message into the orchestrator's near-real-time inbox.

    Only available after plan approval — raises ValueError during briefing.
    """
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    if ctx.orchestrator is None:
        raise ValueError("Orchestrator chat is not available during briefing")
    ctx.orchestrator.inject_operator_message(message)
