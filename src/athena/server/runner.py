"""Pipeline thread management and engagement lifecycle — ensemble harness edition.

One engagement at a time. The pipeline runs in a ThreadPoolExecutor so it
does not block the FastAPI event loop. EngagementContext holds all state
the server needs to interact with a running pipeline.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pubsub import pub

from athena import engagement_status, env_vars, topics

from athena.ensemble.loader import load_ensemble
from athena.ensemble.types import LoadedEnsemble
from athena.harness.committee_runner import LoopGateHooks
from athena.server.manifest import serialise_ensemble
from athena.harness.orchestrator import OrchestratorHarness
from athena.harness.workflow import GLOBAL_STEP_BUDGET, run_workflow
from athena.model_backend import make_backend
from athena.utils import new_id

###############
# CONSTS / GLOBALS #
###############

_log = logging.getLogger("athena.server.runner")

ORCHESTRATOR_AGENT_ID = "athena.orchestrator"

# Re-exported from engagement_status so callers that already import runner can still
# use runner.AWAIT_* without an additional import.
AWAIT_NONE = engagement_status.AWAIT_NONE
AWAIT_PLAN = engagement_status.AWAIT_PLAN
AWAIT_COMMITTEE_GATE = engagement_status.AWAIT_COMMITTEE_GATE
AWAIT_LOOP_GATE = engagement_status.AWAIT_LOOP_GATE

ASK_USER_TIMEOUT_SEC=300

# TODO
# One engagement at a time. NOTE: this worker count is NOT the real one-at-a-time gate —
# is_busy() in start_engagement rejects a second engagement before it is ever submitted
# (that check runs synchronously on the event loop, so it is race-free). Bumping max_workers
# alone therefore does nothing: the extra worker sits idle. True concurrency also requires,
# in order: (1) a multi-run UI + operator model (the dashboard and the blocking operator gates
# assume a single active run), then (2) turning is_busy() into a capacity gate. Per-run state
# is already isolated (EngagementContext, backends, artifacts/{run_id}/, and the SSE bus which
# routes by run_id), so the blockers are the UI/operator model and shared endpoint rate limits.
_executor = ThreadPoolExecutor(max_workers=1)
_active: dict[str, "EngagementContext"] = {}


###############
# CUSTOM TYPES #
###############

@dataclass
class EngagementContext:
    """All mutable server-side state for one running engagement.

    Created by start_engagement() and stored in the _active dict. The pipeline
    worker thread reads and writes status and await_phase; route handlers read
    them and write decision fields before signalling the appropriate threading.Event
    to unblock the worker. All cross-thread access is inherently racy but safe in
    practice because only one worker runs at a time and events serialize decisions.
    """

    run_id: str
    status: str   # one of the engagement_status.* string constants

    reply_event: threading.Event
    plan_decision_event: threading.Event
    gate_decision_event: threading.Event
    loop_gate_event: threading.Event
    await_phase: str   # one of the AWAIT_* constants
    leader_queues: dict[str, queue.Queue]
    # committee -> set of armed in-loop gate kinds ("element" | "step" | "tool").
    armed_gates: dict[str, set[str]]
    # Optional state (None-defaulted fields must follow required fields)
    # Set once the orchestrator loop thread starts (after plan approval).
    orchestrator: OrchestratorHarness | None = None
    pending_question: str | None = None
    pending_answer: str | None = None
    plan_decision_type: str | None = None
    revision_message: str | None = None
    # Committee-gate decision (operator-authoritative Accept / Redo). Distinct from
    # the plan-approval channel above — a committee gate never overlaps briefing.
    gate_decision_action: str | None = None       # "accept" | "redo"
    gate_decision_suggestion: str | None = None   # operator's Redo note
    # Committee + digest of the gate currently awaiting a decision — None when no gate is
    # pending. Read by the gate-decision route to build the collaborator co-approval email.
    gate_committee: str | None = None
    gate_digest: str | None = None
    # In-loop gate decision: {"action": ..., **kind-specific fields}.
    loop_gate_decision: dict | None = None
    # The loaded ensemble for this run — set at start, used by the manifest-summary route.
    ensemble: LoadedEnsemble | None = None
    # Compound keys "{committee}/{element_id}/{specialist_id}" for disabled specialists.
    # Forward-only: takes effect on the next committee that hasn't started yet.
    disabled_specialists: set[str] = None  # type: ignore[assignment]
    # Set True by abort_engagement(); handlers raise EngagementAborted after their wait
    # so the worker unwinds. Read on the worker thread, written on a route thread.
    cancelled: bool = False

    def __post_init__(self) -> None:
        if self.disabled_specialists is None:
            self.disabled_specialists = set()

    @property
    def awaiting_approval(self) -> bool:
        """True while blocked on any operator decision. Kept for callers that only
        need 'is a decision pending' without caring which phase (e.g. chat routing)."""
        return self.await_phase != AWAIT_NONE


###############
# CLASSES #
###############

class EngagementAborted(Exception):
    """Raised inside the worker thread when the operator restarts/abandons a run, so the
    workflow unwinds and frees the single worker instead of holding it (demo Restart)."""
    pass


###############
# FUNCTIONS #
###############

def _orchestrator_backend_config() -> dict:
    """Parse ATHENA_SRV_ORCHESTRATOR_CONFIG (a required JSON object) into a make_backend() config dict.

    Set it to "{}" when the provider needs no options (e.g. Anthropic, which reads its key from
    env). A non-Anthropic provider (e.g. ollama) carries ollama_base_url and extra_headers here;
    make_backend ignores keys it doesn't recognise. Bombs if unset, blank, or not a JSON object.
    """
    raw = env_vars.get_required(env_vars.SRV_ORCHESTRATOR_CONFIG)
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{env_vars.SRV_ORCHESTRATOR_CONFIG} is not valid JSON: {e}") from e
    if not isinstance(cfg, dict):
        raise RuntimeError(
            f"{env_vars.SRV_ORCHESTRATOR_CONFIG} must be a JSON object, got {type(cfg).__name__}"
        )
    return cfg


def get_context(run_id: str) -> EngagementContext | None:
    return _active.get(run_id)


def is_busy() -> bool:
    return any(ctx.status == engagement_status.RUNNING for ctx in _active.values())


def start_engagement(instructions: str) -> str:
    """Start a new engagement. Returns the pre-generated run_id."""
    orch_model = env_vars.get_required(env_vars.SRV_ORCHESTRATOR_MODEL)
    orch_provider = env_vars.get_required(env_vars.SRV_ORCHESTRATOR_PROVIDER)
    orch_config = _orchestrator_backend_config()  # all three bomb here (at the API) if unset/malformed
    if is_busy():
        raise RuntimeError("An engagement is already in progress")

    ensemble_path = _resolve_ensemble_path()
    ensemble = load_ensemble(ensemble_path)

    run_id = new_id()
    ctx = EngagementContext(
        run_id=run_id,
        status=engagement_status.RUNNING,
        reply_event=threading.Event(),
        plan_decision_event=threading.Event(),
        gate_decision_event=threading.Event(),
        loop_gate_event=threading.Event(),
        await_phase=AWAIT_NONE,
        leader_queues={},
        armed_gates={},
        ensemble=ensemble,
    )
    _active[run_id] = ctx

    def _ask_user_handler(question: str) -> str:
        ctx.pending_question = question
        ctx.reply_event.clear()
        pub.sendMessage(topics.ORCHESTRATOR_QUESTION, run_id=run_id, question=question)
        answered = ctx.reply_event.wait(timeout=ASK_USER_TIMEOUT_SEC)
        if ctx.cancelled:
            raise EngagementAborted()
        ctx.pending_question = None
        if not answered:
            return "No operator response within timeout; proceed with best judgement."
        answer = ctx.pending_answer or ""
        ctx.pending_answer = None
        return answer

    def _gate_handler(committee: str, digest: str, redo_available: bool) -> tuple[str, str | None]:
        # Operator-authoritative committee gate. Blocks until the operator decides via
        # resolve_gate_decision(). No timeout — the gate holds until the operator acts,
        # matching the plan-approval gate. The awaiting flag is set BEFORE publishing
        # gate.awaiting_approval so a fast operator POST can't 409 the decision.
        ctx.await_phase = AWAIT_COMMITTEE_GATE
        ctx.gate_decision_action = None
        ctx.gate_decision_suggestion = None
        ctx.gate_committee = committee
        ctx.gate_digest = digest
        ctx.gate_decision_event.clear()
        pub.sendMessage(
            topics.GATE_AWAITING_APPROVAL,
            run_id=run_id,
            committee=committee,
            digest=digest,
            redo_available=redo_available,
        )
        ctx.gate_decision_event.wait()
        ctx.await_phase = AWAIT_NONE
        ctx.gate_committee = None
        ctx.gate_digest = None
        if ctx.cancelled:
            raise EngagementAborted()
        return (ctx.gate_decision_action or "accept", ctx.gate_decision_suggestion)

    loop_gate_lock = threading.Lock()

    def _loop_gate_handler(kind: str, committee: str, payload: dict) -> dict:
        # In-loop operator gate (element / step / tool). Same rendezvous discipline as
        # the committee gate: mark the phase and clear the event BEFORE publishing
        # loop_gate.awaiting, so a fast operator POST can't be lost or race the flag.
        #
        # The lock serializes concurrent gates: a compare-mode element runs its
        # specialists in PARALLEL, so two tool-call gates can fire at once. Without the
        # lock they would trample the single decision slot (event / phase / decision).
        # The lock makes the operator decide them one at a time.
        with loop_gate_lock:
            ctx.await_phase = AWAIT_LOOP_GATE
            ctx.loop_gate_decision = None
            ctx.loop_gate_event.clear()
            pub.sendMessage(
                topics.LOOP_GATE_AWAITING,
                run_id=run_id,
                kind=kind,
                committee=committee,
                payload=payload,
            )
            try:
                ctx.loop_gate_event.wait()
                if ctx.cancelled:
                    raise EngagementAborted()
                decision = ctx.loop_gate_decision or {"action": "accept"}
            finally:
                # Always clear the phase, even if the wait is interrupted, so a stuck
                # AWAIT_LOOP_GATE can't wedge the routes' phase guards (H16).
                ctx.await_phase = AWAIT_NONE
            pub.sendMessage(
                topics.LOOP_GATE_RESOLVED,
                run_id=run_id,
                kind=kind,
                committee=committee,
                action=decision.get("action", "accept"),
            )
            return decision

    def _is_gate_armed(kind: str, committee: str) -> bool:
        return kind in ctx.armed_gates.get(committee, set())

    loop_gate_hooks = LoopGateHooks(is_armed=_is_gate_armed, decide=_loop_gate_handler)

    def _read_artifact_fn(name: str) -> str:
        artifacts_dir = Path("artifacts") / run_id
        path = artifacts_dir / f"{name}.json"
        if not path.exists():
            return f"No artifact found for '{name}'"
        return path.read_text()

    def _run() -> None:
        try:
            pub.sendMessage(
                topics.ENGAGEMENT_STARTED,
                run_id=run_id,
                ensemble=ensemble.name,
                version=ensemble.version,
            )

            orch_backend = make_backend(orch_provider, orch_config)
            orchestrator = OrchestratorHarness(
                backend=orch_backend,
                model=orch_model,
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

                ctx.await_phase = AWAIT_PLAN
                ctx.plan_decision_type = None
                ctx.revision_message = None
                ctx.plan_decision_event.clear()
                ctx.plan_decision_event.wait()
                ctx.await_phase = AWAIT_NONE

                if ctx.cancelled:
                    raise EngagementAborted()

                if ctx.plan_decision_type == "revise":
                    orchestrator.inject_revision(ctx.revision_message or "Please revise.")
                    pub.sendMessage(topics.ENGAGEMENT_PLAN_REVISION, run_id=run_id)
                    continue

                if ctx.plan_decision_type != "approve":
                    pub.sendMessage(
                        topics.ENGAGEMENT_REJECTED, run_id=run_id, reason="Operator rejected the plan"
                    )
                    ctx.status = engagement_status.REJECTED
                    return

                break

            pub.sendMessage(topics.ENGAGEMENT_APPROVED, run_id=run_id)

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
                    gate_handler=_gate_handler,
                    leader_queues=ctx.leader_queues,
                    global_step_budget=GLOBAL_STEP_BUDGET,
                    loop_gate_hooks=loop_gate_hooks,
                    get_disabled_specialists=lambda: frozenset(ctx.disabled_specialists),
                )
            finally:
                orchestrator.stop()
                orch_thread.join(timeout=30)

            ctx.status = engagement_status.COMPLETED

        except EngagementAborted:
            _log.info("engagement %s aborted by operator (restart)", run_id)
            ctx.status = engagement_status.ABANDONED
            pub.sendMessage(topics.ENGAGEMENT_ABORTED, run_id=run_id)
        except Exception:
            _log.exception("engagement %s failed", run_id)
            pub.sendMessage(topics.ENGAGEMENT_REJECTED, run_id=run_id, reason="Internal error")
            ctx.status = engagement_status.FAILED

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
    pub.sendMessage(topics.ORCHESTRATOR_ANSWER, run_id=run_id, answer=answer)


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


def resolve_gate_decision(run_id: str, *, action: str, suggestion: str | None) -> None:
    """Release a committee-gate. action is "accept" or "redo"; suggestion is the
    operator's Redo note (ignored for accept)."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    ctx.gate_decision_action = action
    ctx.gate_decision_suggestion = suggestion
    ctx.gate_decision_event.set()


def abort_engagement(run_id: str) -> None:
    """Abandon a running engagement (demo Restart). Marks it non-running so a fresh
    engagement can start, and unblocks every wait so the worker thread unwinds via
    EngagementAborted instead of holding the single ThreadPoolExecutor slot.

    Note: if the worker is mid-LLM-call (not blocked on a wait) it finishes that call
    before hitting the next cancellation check — acceptable for a single-operator demo.
    """
    ctx = _active.get(run_id)
    if ctx is None:
        return
    ctx.cancelled = True
    ctx.status = engagement_status.ABANDONED
    # Wake anything the worker might be blocked on so it can observe `cancelled`.
    # This covers the "paused, waiting for the operator" states — briefing approval,
    # committee/in-loop gates, orchestrator questions — which is when Restart is normally
    # pressed. A leader blocked in ask_operator (operator_queue.get) still has its own
    # 300s timeout, and a mid-LLM-call worker finishes that call first; both then hit the
    # next cancellation check. is_busy() is already False, so the next engagement can start.
    ctx.reply_event.set()
    ctx.plan_decision_event.set()
    ctx.gate_decision_event.set()
    ctx.loop_gate_event.set()


def resolve_loop_gate_decision(
    run_id: str, *, action: str, payload: dict | None = None
) -> None:
    """Release an in-loop gate (element / step / tool). action is the operator's
    choice ("accept" / "override" / "redo" / "approve" / "deny" / …); payload carries
    any kind-specific fields (e.g. {"winner_id": ...} for an element override)."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    ctx.loop_gate_decision = {"action": action, **(payload or {})}
    ctx.loop_gate_event.set()


def arm_gate(run_id: str, committee: str, kind: str, *, armed: bool) -> None:
    """Arm or disarm an in-loop gate kind for a committee (forward-only: takes effect
    on the next matching tool call). Runtime observation mode — deliberately NOT routed
    through the orchestrator plan (see projects/202607/HARNESS.md §7)."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    kinds = ctx.armed_gates.setdefault(committee, set())
    if armed:
        kinds.add(kind)
    else:
        kinds.discard(kind)


def send_to_leader(run_id: str, committee_name: str, message: str) -> None:
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    q = ctx.leader_queues.get(committee_name)
    if q is None:
        raise KeyError(f"No leader queue for committee: {committee_name!r}")
    q.put_nowait(message)


def get_manifest_summary(run_id: str) -> dict:
    """Return a JSON-serialisable summary of the ensemble manifest for the briefing tree."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    if ctx.ensemble is None:
        raise ValueError("Ensemble not yet loaded")
    return serialise_ensemble(ctx.ensemble)


def render_artifact(run_id: str, name: str, json_text: str) -> str | None:
    """Render a stored committee artifact to its markdown form via the schema's render_full().

    Returns the markdown, or None when the artifact isn't a renderable committee output (unknown
    committee, no ensemble, no render_full, or the JSON doesn't validate) — the caller falls back
    to the raw JSON.
    """
    ctx = _active.get(run_id)
    if ctx is None or ctx.ensemble is None:
        return None
    committee = ctx.ensemble.committees.get(name)
    if committee is None:
        return None
    schema = committee.output_schema
    if not hasattr(schema, "render_full"):
        return None
    try:
        model = schema.model_validate_json(json_text)
        return model.render_full()
    except Exception:
        return None


def set_specialist_enabled(run_id: str, key: str, *, enabled: bool) -> None:
    """Enable or disable a specialist by compound key '{committee}/{element_id}/{specialist_id}'."""
    ctx = _active.get(run_id)
    if ctx is None:
        raise KeyError(f"No engagement: {run_id!r}")
    if enabled:
        ctx.disabled_specialists.discard(key)
    else:
        ctx.disabled_specialists.add(key)


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


###############
# NON PUBLIC FUNCTIONS #
###############

def _resolve_ensemble_path() -> Path:
    return Path(env_vars.get_required(env_vars.ENS_PATH))
