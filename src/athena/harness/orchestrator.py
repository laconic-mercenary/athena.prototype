"""Orchestrator harness — briefing + gate decision loop.

Manages a single persistent conversation with the Chief Orchestrator agent
across the full engagement lifecycle:

  Phase 1 (briefing): loops until submit_plan() is called → EngagementPlan
  Phase 2 (gates):    injects digest + gate context, gets one gate decision

The orchestrator conversation is never reset — the agent sees the full
engagement trajectory at every gate.
"""

from __future__ import annotations

import logging
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

After 3 retries on the same committee, use ask_operator rather than retrying again.\
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
_GATE_TOOLS = [_ADVANCE_TOOL, _RETRY_TOOL, _ITERATE_TOOL, _GATE_ASK_OPERATOR_TOOL, _READ_ARTIFACT_TOOL]


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
# OrchestratorHarness
# ---------------------------------------------------------------------------

class OrchestratorHarness:
    """Stateful orchestrator — one instance per engagement."""

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
                # Orchestrator produced text without using a tool — nudge it.
                self._backend.inject_user_message(
                    "Please use the available tools. Call submit_plan when ready."
                )
                continue

            results: list[str] = []
            plan_ready: EngagementPlan | None = None

            for tc in response.tool_calls:
                if tc.name == "ask_user":
                    question = tc.input.get("question", "")
                    pub.sendMessage(
                        "orchestrator.question", run_id=self._run_id, question=question
                    )
                    answer = self._ask_user_handler(question)
                    pub.sendMessage(
                        "orchestrator.answer", run_id=self._run_id, answer=answer
                    )
                    results.append(answer)

                elif tc.name == "submit_plan":
                    plan_raw = dict(tc.input.get("plan", {}))
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

    def run_gate(
        self,
        committee_name: str,
        digest: str,
        gate_type: str,
        retry_count: int,
        iterate_count: int,
    ) -> GateDecision:
        """Inject gate context and get a gate decision. Loops until a gate tool is called."""
        context = (
            f"== Gate: {gate_type} — {committee_name} complete ==\n\n"
            f"== Committee digest ==\n{digest}\n\n"
            f"Evaluate against adequacy criteria for the {committee_name!r} committee.\n"
            "Use advance(rationale), retry(to, note, rationale), iterate(to, note, rationale), "
            "or ask_operator(question)."
        )
        if retry_count > 0:
            context += f"\n\n(Retry attempt {retry_count} of 3)"
        if iterate_count > 0:
            context += f"\n\n(Iteration {iterate_count} of 30)"

        self._backend.append_harness_message(context)

        while True:
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
                    committee=committee_name,
                    decision=decision.decision,
                    rationale=decision.rationale,
                    to=decision.to,
                    next_objective=decision.next_objective,
                    attempt=(
                        f"{retry_count} of 3" if retry_count
                        else f"{iterate_count} of 30" if iterate_count
                        else None
                    ),
                )
                return decision
