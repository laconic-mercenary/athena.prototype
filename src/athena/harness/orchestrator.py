"""Orchestrator harness — briefing + gate decision loop.

Manages a single persistent conversation with the Chief Orchestrator agent
across the full engagement lifecycle:

  Phase 1 (briefing): loops until submit_plan() is called → EngagementPlan
  Phase 2 (gates):    persistent loop thread; workflow submits gate events via
                      run_gate() and blocks until the orchestrator decides

The orchestrator conversation is never reset — the agent sees the full
engagement trajectory at every gate. Operator messages arrive in near-real
time via inject_operator_message(); they are processed between gate events on
the loop thread so only one backend.complete() call runs at a time.
"""

from __future__ import annotations

import json
import logging
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pubsub import pub
from pydantic import ValidationError

from athena.engagement_plan import EngagementPlan
from athena.model_backend import ModelBackend, ToolDefinition
from athena.utils import new_id

_log = logging.getLogger("athena.harness.orchestrator")

ORCHESTRATOR_MAX_TOKENS = 4_096

# ---------------------------------------------------------------------------
# Orchestrator system prompt (ensemble-agnostic)
# ---------------------------------------------------------------------------

_ORCHESTRATOR_SYSTEM = """\
You are the Chief Orchestrator — harness-level, not part of any ensemble.
Two phases, one continuous conversation.

== Phase 1: Briefing ==
The capability document arrives in your first message. Read it before responding.
Gather objective, scope, and constraints from the operator. Ask only for what is
missing — the operator is a practitioner.
If the capability doc has a `briefing_required` section, use it as a guide: fill
from the operator's message where possible; ask only for genuinely missing fields.
When ready, call submit_plan. The harness validates immediately; revise and resubmit
on error. Downstream committee objectives may be provisional — refine each at its
gate via advance(). The operator's Proceed gesture is final approval.

submit_plan(plan)    — submit the EngagementPlan (briefing only)
ask_user(question)   — ask the operator a clarifying question

Before calling submit_plan, write a short executive summary (2–4 sentences) in plain
prose: what this engagement will accomplish, which committees will run and in what order,
and any operator-approval gates the plan includes. Do not list JSON fields — write as
if briefing a colleague. This message appears in the operator's briefing chat.

== Phase 2: Gate decisions ==
After each committee, the harness injects its digest. Use one gate tool per gate.
Call read_artifact first if the digest is not enough. Evaluate against the adequacy
criteria in the capability document.

advance(next_objective?, rationale)   — adequate; proceed (close engagement if terminal)
retry(to, note, rationale)            — failed; re-run `to` fresh; note → objective list
iterate(to, note, rationale)          — adequate but improvable; re-run `to` with prior shown
ask_operator(question)                — escalate; pipeline pauses
read_artifact(name)                   — fetch full artifact; read-only; not a gate decision

After 3 retries on the same committee, use ask_operator rather than retrying again.

== Operator messages ==
The operator may message you at any time — between committees or during gate evaluation.
Respond briefly in plain prose. Gate decisions still require the gate tools above.\
"""

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_SUBMIT_PLAN_TOOL = ToolDefinition(
    name="submit_plan",
    description="Submit the EngagementPlan for validation and operator approval.",
    parameters={
        "type": "object",
        "properties": {
            "plan": {
                "type": "object",
                "description": "The EngagementPlan. Do not include engagement_id — the harness assigns it.",
                "properties": {
                    "operator_instructions": {"type": "string"},
                    "committees": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "objective": {"type": "array", "items": {"type": "string"}},
                                "constraints": {"type": "array", "items": {"type": "string"}},
                                "emphasis": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["objective"],
                        },
                    },
                    "gates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "after": {"type": "string"},
                                "type": {"type": "string", "enum": ["operator_approval"]},
                            },
                            "required": ["after", "type"],
                        },
                    },
                },
                "required": ["operator_instructions", "committees"],
            }
        },
        "required": ["plan"],
    },
)

_ASK_USER_TOOL = ToolDefinition(
    name="ask_user",
    description="Ask the operator a clarifying question during briefing.",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
)

_ADVANCE_TOOL = ToolDefinition(
    name="advance",
    description="Committee output is adequate. Proceed to the next committee (or close engagement if terminal).",
    parameters={
        "type": "object",
        "properties": {
            "next_objective": {
                "type": "string",
                "description": "Optional refined objective for the next committee.",
            },
            "rationale": {"type": "string", "description": "One-line reason for advancing."},
        },
        "required": ["rationale"],
    },
)

_RETRY_TOOL = ToolDefinition(
    name="retry",
    description="Committee output failed adequacy criteria. Re-run committee `to` fresh (no prior artifact shown).",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Committee to re-run (must be a declared retry target)."},
            "note": {"type": "string", "description": "Note appended to the committee's objective."},
            "rationale": {"type": "string"},
        },
        "required": ["to", "note", "rationale"],
    },
)

_ITERATE_TOOL = ToolDefinition(
    name="iterate",
    description="Committee output is adequate but can improve. Re-run `to` with prior artifact shown.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "note": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["to", "note", "rationale"],
    },
)

_GATE_ASK_OPERATOR_TOOL = ToolDefinition(
    name="ask_operator",
    description="Escalate to operator — pipeline pauses until the operator replies.",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
)

_READ_ARTIFACT_TOOL = ToolDefinition(
    name="read_artifact",
    description="Fetch a committee's full artifact when the digest is not enough to decide. Read-only.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Committee name."}},
        "required": ["name"],
    },
)

_BRIEFING_TOOLS = [_SUBMIT_PLAN_TOOL, _ASK_USER_TOOL]
_GATE_TOOLS     = [_ADVANCE_TOOL, _RETRY_TOOL, _ITERATE_TOOL, _GATE_ASK_OPERATOR_TOOL, _READ_ARTIFACT_TOOL]
# Chat tools: read_artifact only — gate decision tools must never fire during operator chat.
_CHAT_TOOLS     = [_READ_ARTIFACT_TOOL]

# Hard cap for the operator-chat tool loop: one read_artifact call per committee is the
# realistic maximum, plus one turn to produce the answer. 20 committees would be an
# unusually large ensemble; anything beyond that is a runaway loop.
_CHAT_MAX_TOOL_ITERATIONS = 20


# ---------------------------------------------------------------------------
# Gate decision
# ---------------------------------------------------------------------------

@dataclass
class GateDecision:
    decision: str            # "advance" | "retry" | "iterate"
    rationale: str
    to: str | None = None          # retry/iterate target
    note: str | None = None        # retry/iterate note
    next_objective: str | None = None   # advance refinement


# ---------------------------------------------------------------------------
# Internal event types for the persistent loop inbox
# ---------------------------------------------------------------------------

@dataclass
class _GateRequest:
    committee_name: str
    digest: str
    gate_type: str
    retry_count: int
    iterate_count: int


@dataclass
class _OperatorMessage:
    text: str


@dataclass
class _HarnessUpdate:
    """Inject a harness-level status note into the backend without a model call."""
    text: str


class _Stop:
    """Sentinel: instructs run_loop() to exit cleanly."""


# ---------------------------------------------------------------------------
# OrchestratorHarness
# ---------------------------------------------------------------------------

class OrchestratorHarness:
    """Stateful orchestrator — one instance per engagement.

    Threading model:
      - Briefing (run_briefing) runs on the caller's thread.
      - After briefing, the caller starts run_loop() on a dedicated thread.
      - Workflow calls run_gate() from its thread; run_gate() submits to the
        inbox and blocks on the outbox until the loop thread evaluates.
      - Operator messages arrive via inject_operator_message() from any thread
        and are processed between gate evaluations on the loop thread.
    """

    def __init__(
        self,
        backend: ModelBackend,
        model: str,
        run_id: str,
        ask_user_handler: Callable[[str], str],
        read_artifact_fn: Callable[[str], str],
    ) -> None:
        self._backend = backend
        self._model = model
        self._run_id = run_id
        self._ask_user_handler = ask_user_handler
        self._read_artifact_fn = read_artifact_fn
        self._plan: EngagementPlan | None = None
        # Inbox carries _GateRequest | _OperatorMessage | _Stop.
        # Outbox carries GateDecision | BaseException (exception box for propagation).
        self._inbox: queue.Queue = queue.Queue()
        self._outbox: queue.Queue = queue.Queue()

    # ------------------------------------------------------------------
    # Phase 1: Briefing (runs on caller thread — no loop involved)
    # ------------------------------------------------------------------

    def start_briefing(
        self, ensemble_name: str, version: str, capability: str, operator_message: str
    ) -> None:
        initial = (
            f"== Ensemble: {ensemble_name} v{version} ==\n\n"
            f"{capability}\n\n"
            f"== Operator ==\n{operator_message}"
        )
        self._backend.begin(system=_ORCHESTRATOR_SYSTEM, initial_message=initial)

    def run_briefing(self) -> EngagementPlan:
        """Loop until submit_plan is called. Returns the validated EngagementPlan."""
        while True:
            response = self._backend.complete(
                model=self._model,
                tools=_BRIEFING_TOOLS,
                max_tokens=ORCHESTRATOR_MAX_TOKENS,
            )

            # Only publish prose when the orchestrator is submitting a plan — that's
            # the executive summary case. End-turn text and ask_user preambles are
            # intermediate thinking; the question itself appears via orchestrator.question.
            has_submit_plan = any(tc.name == "submit_plan" for tc in response.tool_calls)
            if response.text and has_submit_plan:
                pub.sendMessage(
                    "orchestrator.message", run_id=self._run_id, text=response.text
                )

            if response.stop_reason == "end_turn":
                self._backend.inject_user_message(
                    "Please use the available tools. Call submit_plan when ready."
                )
                continue

            results: list[str] = []
            plan_ready: EngagementPlan | None = None

            for tc in response.tool_calls:
                if tc.name == "ask_user":
                    question = tc.input.get("question", "")
                    # ask_user_handler is responsible for publishing orchestrator.question
                    # (runner._ask_user_handler does this before blocking). Publishing here
                    # too causes every question to appear twice in the UI.
                    answer = self._ask_user_handler(question)
                    pub.sendMessage(
                        "orchestrator.answer", run_id=self._run_id, answer=answer
                    )
                    results.append(answer)

                elif tc.name == "submit_plan":
                    # The model sometimes passes `plan` as a JSON string (or a malformed
                    # value) instead of an object. Coerce/validate defensively and re-prompt
                    # on failure — a bad submit_plan must never crash the engagement.
                    raw = tc.input.get("plan", {})
                    if isinstance(raw, str):
                        try:
                            raw = json.loads(raw)
                        except (json.JSONDecodeError, ValueError):
                            raw = None
                    if not isinstance(raw, dict):
                        results.append(
                            "submit_plan's 'plan' must be a JSON object with the plan fields, "
                            "not a string or list. Revise and resubmit."
                        )
                    else:
                        plan_raw = dict(raw)
                        plan_raw["engagement_id"] = self._run_id
                        try:
                            plan = EngagementPlan.model_validate(plan_raw)
                            self._plan = plan
                            pub.sendMessage(
                                "engagement.plan_ready",
                                run_id=self._run_id,
                                plan=plan.model_dump(),
                            )
                            results.append(
                                "Plan validated. Awaiting operator approval before the pipeline starts."
                            )
                            plan_ready = plan
                        except ValidationError as exc:
                            results.append(f"Plan validation failed: {exc}. Revise and resubmit.")

                else:
                    results.append(f"Tool '{tc.name}' is not available during briefing.")

            self._backend.record_tool_results(response, results)

            if plan_ready is not None:
                return plan_ready

    def inject_revision(self, message: str) -> None:
        """Inject operator plan-revision feedback before re-running briefing."""
        self._backend.inject_user_message(
            f"== Operator Plan Feedback ==\n{message}\n\n"
            "Please revise the plan based on this feedback and call submit_plan again."
        )

    # ------------------------------------------------------------------
    # Phase 2: Persistent loop (runs on dedicated loop thread)
    # ------------------------------------------------------------------

    def run_loop(self) -> None:
        """Process gate and operator events until stop() is called.

        Terminated by a _Stop sentinel — always sent by runner.py after
        run_workflow() returns (normal or exceptional), so this loop is bounded
        by the engagement lifetime.
        """
        while True:
            event = self._inbox.get()

            if isinstance(event, _Stop):
                break
            elif isinstance(event, _HarnessUpdate):
                self._backend.append_harness_message(event.text)
            elif isinstance(event, _OperatorMessage):
                self._handle_operator_message(event.text)
            elif isinstance(event, _GateRequest):
                try:
                    decision = self._evaluate_gate(event)
                    self._outbox.put(decision)
                except Exception as exc:
                    # Box the exception so run_gate() can re-raise on the workflow thread.
                    self._outbox.put(exc)

    def inject_operator_message(self, text: str) -> None:
        """Enqueue an operator message for near-real-time delivery. Thread-safe."""
        self._inbox.put(_OperatorMessage(text=text))

    def inject_harness_update(self, text: str) -> None:
        """Inject a status note into the orchestrator's context without a model call.

        Use this to keep the orchestrator's backend state accurate when something
        significant happens on the workflow thread (e.g. an operator-approval gate
        pause) that the orchestrator model wouldn't otherwise know about.
        Thread-safe.
        """
        self._inbox.put(_HarnessUpdate(text=text))

    def stop(self) -> None:
        """Signal the loop to exit after finishing any current event. Thread-safe."""
        self._inbox.put(_Stop())

    # ------------------------------------------------------------------
    # Gate submission (called from workflow thread)
    # ------------------------------------------------------------------

    def run_gate(
        self,
        committee_name: str,
        digest: str,
        gate_type: str,
        retry_count: int,
        iterate_count: int,
    ) -> GateDecision:
        """Submit a gate request to the loop thread and block until decided."""
        self._inbox.put(_GateRequest(
            committee_name=committee_name,
            digest=digest,
            gate_type=gate_type,
            retry_count=retry_count,
            iterate_count=iterate_count,
        ))
        result = self._outbox.get()
        if isinstance(result, BaseException):
            raise result
        return result

    # ------------------------------------------------------------------
    # Private: operator chat between gates
    # ------------------------------------------------------------------

    def _handle_operator_message(self, text: str) -> None:
        self._backend.inject_user_message(f"[OPERATOR]: {text}")
        # Loop so the orchestrator can call read_artifact before answering.
        # Gate decision tools (advance/retry/iterate) are deliberately excluded.
        for _ in range(_CHAT_MAX_TOOL_ITERATIONS):
            response = self._backend.complete(
                model=self._model,
                tools=_CHAT_TOOLS,
                max_tokens=ORCHESTRATOR_MAX_TOKENS,
            )
            if response.text:
                pub.sendMessage(
                    "orchestrator.message", run_id=self._run_id, text=response.text
                )
            if response.stop_reason == "end_turn":
                return
            results: list[str] = []
            for tc in response.tool_calls:
                if tc.name == "read_artifact":
                    name = tc.input.get("name", "")
                    try:
                        results.append(self._read_artifact_fn(name))
                    except Exception as exc:
                        results.append(f"Error reading artifact '{name}': {exc}")
                else:
                    results.append(f"Tool '{tc.name}' is not available during operator chat.")
            self._backend.record_tool_results(response, results)

    # ------------------------------------------------------------------
    # Private: gate evaluation (runs on loop thread)
    # ------------------------------------------------------------------

    def _evaluate_gate(self, req: _GateRequest) -> GateDecision:
        """Inject gate context and loop until the orchestrator calls a gate tool."""
        context = (
            f"== Gate: {req.gate_type} — {req.committee_name} complete ==\n\n"
            f"== Committee digest ==\n{req.digest}\n\n"
            f"Evaluate against adequacy criteria for the {req.committee_name!r} committee.\n"
            "Use advance(rationale), retry(to, note, rationale), iterate(to, note, rationale), "
            "or ask_operator(question)."
        )
        if req.retry_count > 0:
            context += f"\n\n(Retry attempt {req.retry_count} of 3)"
        if req.iterate_count > 0:
            context += f"\n\n(Iteration {req.iterate_count} of 30)"

        self._backend.append_harness_message(context)

        while True:
            # Drain any operator messages that arrived while we were waiting for
            # the gate event, so they appear in context before the model decides.
            self._drain_operator_messages()

            response = self._backend.complete(
                model=self._model,
                tools=_GATE_TOOLS,
                max_tokens=ORCHESTRATOR_MAX_TOKENS,
            )

            if response.stop_reason == "end_turn":
                self._backend.append_harness_message(
                    "Please use one of the gate tools: advance, retry, iterate, or ask_operator."
                )
                continue

            results: list[str] = []
            decision: GateDecision | None = None

            for tc in response.tool_calls:
                if tc.name == "advance":
                    decision = GateDecision(
                        decision="advance",
                        rationale=tc.input.get("rationale", ""),
                        next_objective=tc.input.get("next_objective"),
                    )
                    results.append("Gate advanced.")

                elif tc.name == "retry":
                    decision = GateDecision(
                        decision="retry",
                        rationale=tc.input.get("rationale", ""),
                        to=tc.input.get("to"),
                        note=tc.input.get("note"),
                    )
                    results.append("Retry scheduled.")

                elif tc.name == "iterate":
                    decision = GateDecision(
                        decision="iterate",
                        rationale=tc.input.get("rationale", ""),
                        to=tc.input.get("to"),
                        note=tc.input.get("note"),
                    )
                    results.append("Iteration scheduled.")

                elif tc.name == "ask_operator":
                    question = tc.input.get("question", "")
                    pub.sendMessage(
                        "orchestrator.question", run_id=self._run_id, question=question
                    )
                    answer = self._ask_user_handler(question)
                    pub.sendMessage(
                        "orchestrator.answer", run_id=self._run_id, answer=answer
                    )
                    results.append(answer)

                elif tc.name == "read_artifact":
                    name = tc.input.get("name", "")
                    try:
                        content = self._read_artifact_fn(name)
                        results.append(content)
                    except Exception as exc:
                        results.append(f"Error reading artifact '{name}': {exc}")

                else:
                    results.append(f"Unknown gate tool '{tc.name}'.")

            self._backend.record_tool_results(response, results)

            if decision is not None:
                pub.sendMessage(
                    "gate.decision",
                    run_id=self._run_id,
                    committee=req.committee_name,
                    decision=decision.decision,
                    rationale=decision.rationale,
                    to=decision.to,
                    next_objective=decision.next_objective,
                    attempt=(
                        f"{req.retry_count} of 3" if req.retry_count
                        else f"{req.iterate_count} of 30" if req.iterate_count
                        else None
                    ),
                )
                # Narrate the gate decision in the operator chat thread so the
                # operator can see what was decided and why without having to ask.
                narrative = f"[{req.committee_name}] Gate: {decision.decision.upper()}"
                if decision.rationale:
                    narrative += f" — {decision.rationale}"
                pub.sendMessage("orchestrator.message", run_id=self._run_id, text=narrative)
                return decision

    def _drain_operator_messages(self) -> None:
        """Non-blocking drain of any operator messages queued in the inbox.

        Called at the top of each gate evaluation iteration so that messages
        sent during committee execution land in context before the model decides.
        """
        while True:
            try:
                event = self._inbox.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, _OperatorMessage):
                self._backend.inject_user_message(f"[OPERATOR]: {event.text}")
            else:
                # Non-message event (gate or stop) — put it back and stop draining.
                # This should not occur in practice since drain is only called from
                # within _evaluate_gate(), but guard against ordering surprises.
                self._inbox.put(event)
                break
