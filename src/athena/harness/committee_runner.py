"""Committee runner — the core Phase 1 loop.

Runs a single committee: builds the leader's initial brief, drives the
submit_step / finish loop, executes each Step's Tasks by running specialist
agents, and synthesises the typed committee artifact at finish().

Public entry point: run_committee_with_ensemble().
Returns (artifact, incomplete: bool).
"""

from __future__ import annotations

import json
import logging
import queue
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pubsub import pub
from pydantic import BaseModel, ValidationError

from athena.agent_loop import SYNTHESIS_MAX_TOKENS, run_agent
from athena.committees.plan import CommitteeStep, CommitteeTask
from athena.engagement_plan import CommitteeBrief
from athena.ensemble.types import LoadedCommittee, LoadedElement, LoadedEnsemble, LoadedSkill
from athena.harness.skill_executor import execute_skill, skill_to_tool_def
from athena.model_backend import ModelBackend, ToolDefinition
from athena.utils import extract_json, new_id

_log = logging.getLogger("athena.harness.committee_runner")

BackendFactory = Callable[[str, "str | None"], ModelBackend]


@dataclass
class LoopGateHooks:
    """Operator control over gates that fire *inside* a leader's turn (the in-loop
    gate family — see projects/202607/HARNESS.md). Unlike the between-committee gate
    in workflow.py, these pause on a single tool call and stay within the leader's
    turn (no graph traversal).

    - is_armed(kind, committee) -> bool: is this gate kind armed for this committee?
      (Cheap; consulted at every candidate tool call, so it must be fast.)
    - decide(kind, committee, payload) -> dict: block on the operator and return the
      decision, e.g. {"action": "accept"} / {"action": "override", "winner_id": ...}
      / {"action": "redo"}. Only called when is_armed returned True.

    kind is one of "element", "step", "tool". None-safe: when the hooks object is
    absent the runner behaves exactly as before (no gating).
    """

    is_armed: Callable[[str, str], bool]
    decide: Callable[[str, str, dict], dict]


def _apply_element_gate(
    hooks: "LoopGateHooks | None",
    committee_name: str,
    *,
    element_id: str,
    winner_id: str,
    rationale: str,
    variants: list[dict],
    valid_ids: set[str],
) -> "tuple[str, str | None, str | None]":
    """Consult the operator element gate for a select_result call.

    Pure and side-effect-free (all blocking/publishing lives in hooks.decide), so it
    is unit-testable in isolation. Returns (winner_id, reprompt, note):
    - reprompt not None -> the operator asked to re-select; the dispatch should return
      this string so the leader calls select_result again (no selection recorded).
    - otherwise winner_id is the final (possibly overridden) selection and note is an
      optional suffix appended to the tool result.
    """
    if hooks is None or not hooks.is_armed("element", committee_name):
        return winner_id, None, None

    decision = hooks.decide(
        "element",
        committee_name,
        {
            "element_id": element_id,
            "winner_id": winner_id,
            "rationale": rationale,
            "variants": variants,
        },
    )
    action = (decision.get("action") or "accept").strip().lower()

    if action == "redo":
        return winner_id, (
            "Operator requested a different selection. Re-evaluate the variants and "
            "call select_result again with your revised choice."
        ), None

    if action == "override":
        new_id = (decision.get("winner_id") or "").strip()
        if new_id and new_id in valid_ids:
            return new_id, None, f"Operator overrode the winner to {new_id!r}."
        # Invalid override target (stale client): fail safe to the leader's choice.
        _log.warning(
            "Element gate override to unknown winner %r on %r; keeping %r.",
            new_id, committee_name, winner_id,
        )

    return winner_id, None, None


def _apply_tool_gate(
    hooks: "LoopGateHooks | None",
    committee_name: str,
    *,
    tool: str,
    args: dict,
    side_effect: str,
) -> "tuple[bool, str | None]":
    """Consult the operator tool-call authorization gate BEFORE a domain tool runs.

    Returns (approved, deny_reason). When the gate is disarmed this is a fast no-op
    that approves. On deny the caller must NOT execute the tool and should hand the
    specialist a clear, actionable denial (denial is a first-class outcome — the
    specialist adapts, it is not an error). See HARNESS.md §4/§6.
    """
    if hooks is None or not hooks.is_armed("tool", committee_name):
        return True, None

    decision = hooks.decide(
        "tool", committee_name, {"tool": tool, "args": args, "side_effect": side_effect}
    )
    action = (decision.get("action") or "approve").strip().lower()
    if action == "deny":
        reason = (decision.get("reason") or decision.get("suggestion") or "").strip()
        return False, reason or "Operator denied this action."
    return True, None


def _apply_step_gate(
    hooks: "LoopGateHooks | None",
    committee_name: str,
    *,
    step_id: str,
    description: str,
    digest: str,
) -> "tuple[str, str | None]":
    """Consult the operator post-step quality gate AFTER a step's work completes.

    Returns (outcome, note): outcome is "accept" (step stands) / "redo" (leader should
    revise and resubmit; note carries the operator's suggestion) / "skip" (accept as-is
    and move on). Disarmed -> ("accept", None). See HARNESS.md §3.
    """
    if hooks is None or not hooks.is_armed("step", committee_name):
        return "accept", None

    decision = hooks.decide(
        "step", committee_name, {"step_id": step_id, "description": description, "digest": digest}
    )
    action = (decision.get("action") or "accept").strip().lower()
    if action == "redo":
        return "redo", (decision.get("suggestion") or "").strip() or None
    if action == "skip":
        return "skip", None
    return "accept", None

# Specialist agents run tight, bounded loops — they have a single well-scoped task.
SPECIALIST_MAX_ITERATIONS = 30
SPECIALIST_MAX_TOKENS = 4_096
# Hard cap on how many real skill calls a single specialist may EXECUTE per run.
# Prevents models from calling the same skill twice to "verify" results. A denied
# tool call does NOT count against this (see SPECIALIST_MAX_TOOL_ATTEMPTS).
SPECIALIST_MAX_TOOL_CALLS = 1
# Cap on total tool ATTEMPTS (executed + operator-denied). Denials don't consume the
# executed budget above — so the specialist can propose a different action after a deny
# — but this bounds the number of operator prompts a single specialist can generate (H14).
SPECIALIST_MAX_TOOL_ATTEMPTS = 3

# Leaders plan across many steps and may iterate; they need a higher ceiling.
LEADER_MAX_ITERATIONS = 500

# SSE payload truncation — keeps the event stream lean without losing actionable info.
TOOL_INPUT_SUMMARY_MAX_LEN = 500
TOOL_RESULT_MAX_LEN = 2_000
TASK_OUTPUT_SUMMARY_MAX_LEN = 300
AGENT_TEXT_EVENT_MAX_LEN = 2_000
# Per-variant output preview sent to the element gate so the operator can actually
# compare what each variant produced before confirming/overriding the winner (H10).
ELEMENT_GATE_OUTPUT_PREVIEW_MAX_LEN = 600


class RefuseStartError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Tool definitions — leader tools
# ---------------------------------------------------------------------------

_SUBMIT_STEP_TOOL = ToolDefinition(
    name="submit_step",
    description=(
        "Submit the next Step for execution. The harness runs all Tasks sequentially "
        "and returns their outputs. Use this to plan and execute one step at a time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "One-line description of what this Step does and why.",
            },
            "tasks": {
                "type": "array",
                "description": "Tasks to execute. Each names an element and provides its brief.",
                "items": {
                    "type": "object",
                    "properties": {
                        "element": {
                            "type": "string",
                            "description": "Element id from the committee element inventory.",
                        },
                        "brief": {
                            "type": "string",
                            "description": "Assignment written for this element.",
                        },
                    },
                    "required": ["element", "brief"],
                },
            },
            "supersedes": {
                "type": "array",
                "description": "IDs of prior Steps whose outputs this Step replaces.",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["description", "tasks"],
    },
)

_FINISH_TOOL = ToolDefinition(
    name="finish",
    description="The objective is met. Call this to trigger final artifact synthesis.",
    parameters={"type": "object", "properties": {}, "required": []},
)

_REFUSE_START_TOOL = ToolDefinition(
    name="refuse_start",
    description="The assigned objective is unclear or impossible. The engagement halts.",
    parameters={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why the objective cannot be pursued."}
        },
        "required": ["reason"],
    },
)

_ASK_OPERATOR_TOOL = ToolDefinition(
    name="ask_operator",
    description="Pause and surface a question to the operator. Returns their answer.",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
)

_REPLY_OPERATOR_TOOL = ToolDefinition(
    name="reply_operator",
    description="Send a reply to an operator chat message without advancing work.",
    parameters={
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
    },
)

_READ_ARTIFACT_TOOL = ToolDefinition(
    name="read_artifact",
    description="Fetch the full rendered artifact of an optional upstream committee.",
    parameters={
        "type": "object",
        "properties": {
            "committee": {
                "type": "string",
                "description": "Name of the optional upstream committee.",
            }
        },
        "required": ["committee"],
    },
)

_SELECT_RESULT_TOOL = ToolDefinition(
    name="select_result",
    description=(
        "After receiving compare-mode outputs, record which variant you selected and why. "
        "Call this once per compare element before calling finish()."
    ),
    parameters={
        "type": "object",
        "properties": {
            "winner_id": {
                "type": "string",
                "description": "Exact label of the selected variant as shown in the compare output (e.g. 'Hidden File Counter (t=0.0)').",
            },
            "rationale": {
                "type": "string",
                "description": "One or two sentences explaining why this variant was chosen over the others.",
            },
        },
        "required": ["winner_id", "rationale"],
    },
)


# ---------------------------------------------------------------------------
# Brief builder
# ---------------------------------------------------------------------------

def _build_leader_brief(
    committee: LoadedCommittee,
    brief: CommitteeBrief,
    prior_artifacts: dict[str, BaseModel],
    *,
    is_retry: bool,
    is_iterate: bool,
    prior_artifact: BaseModel | None = None,
) -> str:
    sections: list[str] = []

    obj_lines = "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(brief.objective))
    brief_block = f"== Engagement brief ==\nObjective:\n{obj_lines}"
    if brief.constraints:
        brief_block += "\nConstraints: " + "; ".join(brief.constraints)
    if brief.emphasis:
        brief_block += "\nEmphasis: " + "; ".join(brief.emphasis)
    sections.append(brief_block)

    upstream_parts: list[str] = []
    for dep in committee.consumes_required:
        artifact = prior_artifacts.get(dep)
        if artifact is not None and hasattr(artifact, "render_full"):
            upstream_parts.append(f"=== {dep} (required) ===\n{artifact.render_full()}")
    for dep in committee.consumes_optional:
        artifact = prior_artifacts.get(dep)
        if artifact is not None and hasattr(artifact, "render_digest"):
            upstream_parts.append(
                f"=== {dep} (optional — call read_artifact('{dep}') for the full artifact) ===\n"
                f"{artifact.render_digest()}"
            )
    if upstream_parts:
        sections.append("== Prior committee outputs ==\n" + "\n\n".join(upstream_parts))

    if is_iterate and prior_artifact is not None and hasattr(prior_artifact, "render_full"):
        sections.append(
            "== Previous output ==\n"
            "Your previous output is acceptable. Refine the following aspect.\n\n"
            + prior_artifact.render_full()
        )

    if committee.playbook:
        sections.append(f"== Your playbook ==\n{committee.playbook}")

    if committee.task_cards:
        cards = "\n\n".join(
            f"=== Element: {eid} ===\n{card}"
            for eid, card in committee.task_cards.items()
        )
        sections.append(f"== Element task cards ==\n{cards}")

    if is_retry:
        sections.append(
            "This is a retry — your previous output did not meet adequacy criteria. "
            "Begin fresh. Submit your first Step."
        )
    elif is_iterate:
        sections.append("This is a refinement. Submit your first Step.")
    else:
        sections.append("Begin: submit your first Step.")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Element / specialist runner
# ---------------------------------------------------------------------------

def _run_one_specialist(
    specialist: LoadedSpecialist,
    task_brief: str,
    skills_map: dict[str, LoadedSkill],
    committee_name: str,
    run_id: str,
    make_backend: BackendFactory,
    agent_id: str,
    element_id: str = "",
    element_label: str = "",
    variant_label: str = "",
    loop_gate_hooks: "LoopGateHooks | None" = None,
) -> str:
    """Run a single specialist agent and return its text output."""
    granted_skills = [skills_map[sid] for sid in specialist.skill_ids if sid in skills_map]
    spec_tools = [skill_to_tool_def(s) for s in granted_skills]
    skills_by_name = {s.name: s for s in granted_skills}

    pub.sendMessage(
        "agent.spawned",
        run_id=run_id,
        committee=committee_name,
        agent_id=agent_id,
        title=specialist.title,
        role="specialist",
        element_id=element_id,
        element_label=element_label or element_id,
        variant_label=variant_label,
    )

    _tool_calls_made = [0]   # executed (approved) calls — capped by SPECIALIST_MAX_TOOL_CALLS
    _tool_attempts = [0]     # executed + denied — capped by SPECIALIST_MAX_TOOL_ATTEMPTS

    def spec_dispatch(name: str, params: dict) -> str:
        skill = skills_by_name.get(name)
        if skill is None:
            return json.dumps({"error": f"Unknown skill: {name}"})
        if _tool_calls_made[0] >= SPECIALIST_MAX_TOOL_CALLS:
            return json.dumps({
                "error": "Tool call limit reached. Use the result you already received and output your final answer now."
            })
        if _tool_attempts[0] >= SPECIALIST_MAX_TOOL_ATTEMPTS:
            return json.dumps({
                "error": "Too many denied attempts. Proceed to your final answer with what you already know."
            })
        _tool_attempts[0] += 1
        call_id = new_id()
        pub.sendMessage(
            "agent.tool_called",
            run_id=run_id,
            committee=committee_name,
            agent_id=agent_id,
            tool=name,
            call_id=call_id,
            input_summary=json.dumps(params, default=str)[:TOOL_INPUT_SUMMARY_MAX_LEN],
        )
        # Tool-call authorization gate (in-loop): the operator may approve or deny this
        # action before it runs. No-op unless the "tool" gate is armed for this committee.
        approved, deny_reason = _apply_tool_gate(
            loop_gate_hooks, committee_name,
            tool=name, args=params,
            side_effect=getattr(skill, "side_effect", "reads_local"),
        )
        if not approved:
            # A denial does NOT consume the executed-call budget — the specialist may
            # propose a different action (bounded by SPECIALIST_MAX_TOOL_ATTEMPTS).
            result = json.dumps({
                "denied": True,
                "reason": deny_reason,
                "note": "Operator denied this action. You may propose a different action, "
                        "or proceed to your final answer with what you already know.",
            })
        else:
            _tool_calls_made[0] += 1
            try:
                result = execute_skill(skill, params)
            except Exception as exc:
                result = json.dumps({"error": str(exc)})
        pub.sendMessage(
            "agent.tool_result",
            run_id=run_id,
            committee=committee_name,
            agent_id=agent_id,
            tool=name,
            call_id=call_id,
            result=result[:TOOL_RESULT_MAX_LEN],
        )
        return result

    def _on_model_response(text: str, stop_reason: str) -> None:
        pub.sendMessage(
            "agent.model_text",
            run_id=run_id,
            committee=committee_name,
            agent_id=agent_id,
            text=text[:AGENT_TEXT_EVENT_MAX_LEN],
            stop_reason=stop_reason,
        )

    backend = make_backend(specialist.provider, None)
    result = run_agent(
        agent_id=agent_id,
        system=specialist.system,
        initial_message=task_brief,
        tools=spec_tools,
        tool_dispatch=spec_dispatch,
        backend=backend,
        model=specialist.model,
        max_iterations=SPECIALIST_MAX_ITERATIONS,
        max_tokens=SPECIALIST_MAX_TOKENS,
        temperature=specialist.temperature,
        on_model_response=_on_model_response,
    )

    pub.sendMessage(
        "agent.spun_down",
        run_id=run_id,
        committee=committee_name,
        agent_id=agent_id,
    )
    return result


def _variant_label(specialist: LoadedSpecialist, idx: int, all_models: list[str]) -> str:
    """Build a human-readable label for one compare-mode variant."""
    meta = []
    if specialist.temperature is not None:
        meta.append(f"t={specialist.temperature}")
    # Show model only when variants differ — avoids noise when all use the same model.
    if len(set(all_models)) > 1:
        meta.append(f"model={specialist.model}")
    suffix = f" ({', '.join(meta)})" if meta else ""
    return f"{specialist.title}{suffix}"


def _run_compare(
    element: LoadedElement,
    task_brief: str,
    skills_map: dict[str, LoadedSkill],
    committee_name: str,
    run_id: str,
    make_backend: BackendFactory,
    compare_sink: dict[str, dict] | None = None,
    loop_gate_hooks: "LoopGateHooks | None" = None,
) -> str:
    """Run all specialists in parallel and return labeled variant output for leader judgement."""
    all_models = [s.model for s in element.specialists]
    # Precompute labels so the same string is used for display, sink keys, and agent.spawned.
    variant_labels = [_variant_label(s, i, all_models) for i, s in enumerate(element.specialists)]

    def run_variant(args: tuple[int, LoadedSpecialist]) -> str:
        idx, specialist = args
        agent_id = f"{run_id}.{committee_name}.{element.id}.v{idx + 1}"
        return _run_one_specialist(
            specialist, task_brief, skills_map,
            committee_name, run_id, make_backend, agent_id,
            element_id=element.id,
            element_label=element.label,
            variant_label=variant_labels[idx],
            loop_gate_hooks=loop_gate_hooks,
        )

    with ThreadPoolExecutor(max_workers=len(element.specialists)) as pool:
        # pool.map preserves input order in its results.
        outputs = list(pool.map(run_variant, enumerate(element.specialists)))

    if compare_sink is not None:
        for label, specialist, output in zip(variant_labels, element.specialists, outputs):
            compare_sink[label] = {"output": output, "title": specialist.title}

    parts = [f"[{label}]\n{output}" for label, output in zip(variant_labels, outputs)]
    return (
        "\n\n---\n\n".join(parts)
        + "\n\n[Select the variant that best meets the task objective. "
        "Call select_result(winner_id, rationale) with the chosen variant's exact label.]"
    )



def _run_element(
    element: LoadedElement,
    task_brief: str,
    skills_map: dict[str, LoadedSkill],
    committee_name: str,
    run_id: str,
    task_id: str,
    make_backend: BackendFactory,
    compare_sink: dict[str, dict] | None = None,
    loop_gate_hooks: "LoopGateHooks | None" = None,
) -> str:
    if len(element.specialists) == 1:
        (specialist,) = element.specialists
        agent_id = f"{run_id}.{committee_name}.{element.id}"
        return _run_one_specialist(
            specialist, task_brief, skills_map,
            committee_name, run_id, make_backend, agent_id,
            element_id=element.id,
            element_label=element.label,
            loop_gate_hooks=loop_gate_hooks,
        )

    return _run_compare(
        element, task_brief, skills_map, committee_name, run_id, make_backend,
        compare_sink=compare_sink, loop_gate_hooks=loop_gate_hooks,
    )


# ---------------------------------------------------------------------------
# Main committee runner
# ---------------------------------------------------------------------------

def run_committee_with_ensemble(
    ensemble: LoadedEnsemble,
    committee_name: str,
    brief: CommitteeBrief,
    prior_artifacts: dict[str, BaseModel],
    artifacts_dir: Path,
    run_id: str,
    make_backend: BackendFactory,
    ask_operator_handler: Callable[[str], str],
    operator_queue: queue.Queue | None = None,
    loop_gate_hooks: LoopGateHooks | None = None,
    *,
    is_retry: bool,
    is_iterate: bool,
    prior_artifact: BaseModel | None = None,
) -> tuple[BaseModel, bool]:
    """Run a committee and return (artifact, incomplete)."""
    committee = ensemble.committees[committee_name]
    skills_map = ensemble.skills

    initial_msg = _build_leader_brief(
        committee,
        brief,
        prior_artifacts,
        is_retry=is_retry,
        is_iterate=is_iterate,
        prior_artifact=prior_artifact,
    )

    schema_name = committee.output_schema.__name__
    element_ids = {e.id for e in committee.elements}

    # Field list for the artifact schema — used by finish() and the end_turn validator.
    _field_list = ", ".join(
        f'"{k}" ({getattr(field.annotation, "__name__", str(field.annotation))})'
        for k, field in committee.output_schema.model_fields.items()
    )

    step_count = [0]
    _finished = [False]
    _incomplete = [False]
    _refuse_reason: list[str | None] = [None]
    _element_compare_outputs: dict[str, dict[str, dict]] = {}  # element_id → {variant_label → {output, title}}

    def _dispatch(name: str, params: dict) -> str:
        if name == "submit_step":
            if step_count[0] >= committee.max_steps:
                _incomplete[0] = True
                return (
                    f"Step cap ({committee.max_steps}) reached. "
                    "You must call finish() now — do not submit more Steps."
                )

            task_defs_raw = params.get("tasks", [])
            for t in task_defs_raw:
                if t.get("element") not in element_ids:
                    return (
                        f"Error: unknown element '{t.get('element')}'. "
                        f"Valid elements: {sorted(element_ids)}"
                    )

            step_id = new_id()
            step_count[0] += 1
            description = params.get("description", "")
            supersedes_ids: list[str] = params.get("supersedes", [])

            tasks = [
                CommitteeTask(element=t["element"], brief=t["brief"])
                for t in task_defs_raw
            ]

            for sid in supersedes_ids:
                pub.sendMessage(
                    "step.superseded",
                    run_id=run_id,
                    committee=committee.name,
                    step_id=sid,
                )

            task_events = [
                {"task_id": new_id(), "element": t.element, "brief": t.brief}
                for t in tasks
            ]
            pub.sendMessage(
                "step.started",
                run_id=run_id,
                committee=committee.name,
                step_id=step_id,
                description=description,
                tasks=task_events,
            )

            task_outputs: list[str] = []
            for task, tevt in zip(tasks, task_events):
                task_id = tevt["task_id"]
                pub.sendMessage(
                    "task.started",
                    run_id=run_id,
                    committee=committee.name,
                    step_id=step_id,
                    task_id=task_id,
                    element=task.element,
                    brief=task.brief,
                )

                element = next(e for e in committee.elements if e.id == task.element)
                compare_sink: dict[str, dict] | None = {} if len(element.specialists) > 1 else None
                output = _run_element(
                    element=element,
                    task_brief=task.brief,
                    skills_map=skills_map,
                    committee_name=committee.name,
                    run_id=run_id,
                    task_id=task_id,
                    make_backend=make_backend,
                    compare_sink=compare_sink,
                    loop_gate_hooks=loop_gate_hooks,
                )
                if compare_sink is not None:
                    _element_compare_outputs[task.element] = compare_sink

                pub.sendMessage(
                    "task.completed",
                    run_id=run_id,
                    committee=committee.name,
                    step_id=step_id,
                    task_id=task_id,
                    summary=output[:TASK_OUTPUT_SUMMARY_MAX_LEN],
                )
                task_outputs.append(f"[{task.element}]\n{output}")

            combined = "\n\n".join(task_outputs)
            pub.sendMessage(
                "step.completed",
                run_id=run_id,
                committee=committee.name,
                step_id=step_id,
            )

            # Post-step quality gate (in-loop): operator may accept / redo / skip the
            # completed step. No-op unless the "step" gate is armed for this committee.
            outcome, note = _apply_step_gate(
                loop_gate_hooks, committee.name,
                step_id=step_id, description=description,
                digest=combined[:TOOL_RESULT_MAX_LEN],
            )
            if outcome == "redo":
                msg = (
                    f"Operator requested a revision of this step: {note}"
                    if note else "Operator requested a revision of this step."
                )
                return (
                    f"{msg} The step's output was not accepted — revise your approach "
                    f"and call submit_step again.\n\n{combined}"
                )
            suffix = "\n\n[Operator skipped review of this step.]" if outcome == "skip" else ""
            return f"Step {step_id} completed.{suffix}\n\n{combined}"

        if name == "select_result":
            winner_id = params.get("winner_id", "")
            rationale = params.get("rationale", "")
            winner_output = ""
            winner_title = ""
            matched_element = ""
            variants: list[dict] = []
            matched_sink: dict[str, dict] | None = None
            for eid, sink in _element_compare_outputs.items():
                if winner_id in sink:
                    winner_output = sink[winner_id]["output"]
                    winner_title = sink[winner_id]["title"]
                    matched_element = eid
                    matched_sink = sink
                    variants = [
                        {"label": lbl, "title": info["title"], "output": info["output"][:TOOL_RESULT_MAX_LEN]}
                        for lbl, info in sink.items()
                    ]
                    break

            # Operator element gate (in-loop): confirm the winner, override it, or ask
            # the leader to re-select. No-op unless the "element" gate is armed.
            winner_id, reprompt, gate_note = _apply_element_gate(
                loop_gate_hooks,
                committee.name,
                element_id=matched_element,
                winner_id=winner_id,
                rationale=rationale,
                variants=[
                    {
                        "label": v["label"],
                        "title": v["title"],
                        "output": v["output"][:ELEMENT_GATE_OUTPUT_PREVIEW_MAX_LEN],
                    }
                    for v in variants
                ],
                valid_ids=set(matched_sink) if matched_sink else set(),
            )
            if reprompt is not None:
                return reprompt
            # An override may have changed the winner — recompute its output/title.
            if matched_sink is not None and winner_id in matched_sink:
                winner_output = matched_sink[winner_id]["output"]
                winner_title = matched_sink[winner_id]["title"]

            pub.sendMessage(
                "committee.result_selected",
                run_id=run_id,
                committee=committee.name,
                element_id=matched_element,
                winner_id=winner_id,
                winner_title=winner_title,
                rationale=rationale,
                result=winner_output[:TOOL_RESULT_MAX_LEN],
                variants=variants,
            )
            return "Selection recorded." + (f" {gate_note}" if gate_note else "")

        if name == "finish":
            _finished[0] = True
            return (
                f"Objective met. Synthesise your final committee artifact now.\n\n"
                f"Your ENTIRE response must be a single raw JSON object — "
                f"no prose, no markdown fences, no surrounding text of any kind.\n"
                f"Required fields: {_field_list}.\n"
                f"String values that contain newlines must be JSON-escaped (\\n)."
            )

        if name == "refuse_start":
            _refuse_reason[0] = params.get("reason", "No reason provided")
            _finished[0] = True
            return "Acknowledged. Engagement halted."

        if name == "ask_operator":
            question = params.get("question", "")
            pub.sendMessage(
                "committee.ask_operator",
                run_id=run_id,
                committee=committee.name,
                question=question,
            )
            if operator_queue is not None:
                try:
                    answer = operator_queue.get(timeout=300)
                except queue.Empty:
                    answer = "No operator response within timeout; proceed with best judgement."
                pub.sendMessage(
                    "committee.operator_replied",
                    run_id=run_id,
                    committee=committee.name,
                )
                return answer
            return ask_operator_handler(question)

        if name == "reply_operator":
            pub.sendMessage(
                "agent.operator_reply",
                run_id=run_id,
                committee=committee.name,
                agent_id=f"{run_id}.{committee.name}.leader",
                text=params.get("message", ""),
            )
            return ""

        if name == "read_artifact":
            if not committee.consumes_optional:
                return "Error: read_artifact not available — no optional dependencies."
            target = params.get("committee", "")
            if target not in committee.consumes_optional:
                return (
                    f"Error: '{target}' is not an optional dependency. "
                    f"Allowed: {committee.consumes_optional}"
                )
            artifact = prior_artifacts.get(target)
            if artifact is None:
                return f"Error: no artifact available for '{target}'"
            return artifact.render_full() if hasattr(artifact, "render_full") else artifact.model_dump_json()

        return f"Error: unknown tool '{name}'"

    def tool_dispatch(name: str, params: dict) -> str:
        call_id = new_id()
        pub.sendMessage(
            "agent.tool_called",
            run_id=run_id, committee=committee.name,
            agent_id=leader_id, tool=name, call_id=call_id,
            input_summary=json.dumps(params, default=str)[:TOOL_INPUT_SUMMARY_MAX_LEN],
        )
        result = _dispatch(name, params)
        pub.sendMessage(
            "agent.tool_result",
            run_id=run_id, committee=committee.name,
            agent_id=leader_id, tool=name, call_id=call_id,
            result=result[:TOOL_RESULT_MAX_LEN],
        )
        return result

    leader_tools = [
        _SUBMIT_STEP_TOOL, _FINISH_TOOL, _REFUSE_START_TOOL,
        _ASK_OPERATOR_TOOL, _REPLY_OPERATOR_TOOL,
    ]
    if committee.consumes_optional:
        leader_tools.append(_READ_ARTIFACT_TOOL)
    if any(len(e.specialists) > 1 for e in committee.elements):
        leader_tools.append(_SELECT_RESULT_TOOL)

    leader_id = f"{run_id}.{committee.name}.leader"
    pub.sendMessage(
        "agent.spawned",
        run_id=run_id,
        committee=committee.name,
        agent_id=leader_id,
        title=f"{committee.name.replace('-', ' ').replace('_', ' ').title()} Leader",
        role="leader",
    )

    def _on_leader_response(text: str, stop_reason: str) -> None:
        pub.sendMessage(
            "agent.model_text",
            run_id=run_id,
            committee=committee.name,
            agent_id=leader_id,
            text=text[:AGENT_TEXT_EVENT_MAX_LEN],
            stop_reason=stop_reason,
        )

    def _validate_end_turn(text: str) -> str | None:
        # The leader must end its turn ONLY to emit the final artifact, which happens
        # after finish(). If it ends conversationally (e.g. after reply_operator), or
        # after finish() but with unparseable JSON, re-prompt instead of crashing on
        # extract_json downstream.
        if _refuse_reason[0] is not None:
            return None  # refused — accept the end_turn; the caller raises RefuseStartError
        if not _finished[0]:
            return (
                "You ended your turn without calling a tool. Do not reply in plain text. "
                "If the objective is met, call finish() to synthesise the final artifact. "
                "If you are waiting on the operator, call ask_operator(). Otherwise call "
                "submit_step() to continue."
            )
        try:
            committee.output_schema.model_validate(extract_json(text))
        except (ValueError, ValidationError) as exc:
            return (
                f"That was not a valid {schema_name} artifact ({str(exc)[:200]}). Resend your "
                f"ENTIRE response as a single raw JSON object with fields: {_field_list}. "
                f"No prose, no markdown fences."
            )
        return None

    backend = make_backend(committee.provider, None)
    artifact_text = run_agent(
        agent_id=leader_id,
        system=committee.leader_system,
        initial_message=initial_msg,
        tools=leader_tools,
        tool_dispatch=tool_dispatch,
        backend=backend,
        model=committee.model,
        max_iterations=LEADER_MAX_ITERATIONS,
        max_tokens=SYNTHESIS_MAX_TOKENS,
        operator_queue=operator_queue,
        on_model_response=_on_leader_response,
        on_end_turn=_validate_end_turn,
    )

    pub.sendMessage(
        "agent.spun_down",
        run_id=run_id,
        committee=committee.name,
        agent_id=leader_id,
    )

    if _refuse_reason[0]:
        raise RefuseStartError(_refuse_reason[0])

    if not _finished[0]:
        _log.warning("%s leader produced end_turn without calling finish()", committee.name)

    # The on_end_turn validator normally guarantees a parseable artifact by the time we
    # get here. This guards the residual case where the correction budget was exhausted,
    # turning a raw ValueError into a clear committee-level failure.
    try:
        raw = extract_json(artifact_text)
        artifact = committee.output_schema.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(
            f"Committee {committee.name!r} did not produce a valid {schema_name} artifact: {exc}"
        ) from exc

    return artifact, _incomplete[0]
