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

# Specialist agents run tight, bounded loops — they have a single well-scoped task.
SPECIALIST_MAX_ITERATIONS = 30
SPECIALIST_MAX_TOKENS = 4_096

# Leaders plan across many steps and may iterate; they need a higher ceiling.
LEADER_MAX_ITERATIONS = 500

# SSE payload truncation — keeps the event stream lean without losing actionable info.
TOOL_INPUT_SUMMARY_MAX_LEN = 500
TASK_OUTPUT_SUMMARY_MAX_LEN = 300
AGENT_TEXT_EVENT_MAX_LEN = 2_000


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
    skill_ids: list[str],
    task_brief: str,
    skills_map: dict[str, LoadedSkill],
    committee_name: str,
    run_id: str,
    make_backend: BackendFactory,
    agent_id: str,
) -> str:
    """Run a single specialist agent and return its text output."""
    granted_skills = [skills_map[sid] for sid in skill_ids if sid in skills_map]
    spec_tools = [skill_to_tool_def(s) for s in granted_skills]
    skills_by_name = {s.name: s for s in granted_skills}

    pub.sendMessage(
        "agent.spawned",
        run_id=run_id,
        committee=committee_name,
        agent_id=agent_id,
        title=specialist.id,
        role="specialist",
    )

    def spec_dispatch(name: str, params: dict) -> str:
        skill = skills_by_name.get(name)
        if skill is None:
            return json.dumps({"error": f"Unknown skill: {name}"})
        pub.sendMessage(
            "agent.tool_called",
            run_id=run_id,
            committee=committee_name,
            agent_id=agent_id,
            tool=name,
            input_summary=json.dumps(params, default=str)[:TOOL_INPUT_SUMMARY_MAX_LEN],
        )
        try:
            return execute_skill(skill, params)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

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
    return f"Variant {idx + 1} — {specialist.id}{suffix}"


def _run_compare(
    element: LoadedElement,
    task_brief: str,
    skills_map: dict[str, LoadedSkill],
    committee_name: str,
    run_id: str,
    make_backend: BackendFactory,
) -> str:
    """Run all specialists in parallel and return labeled variant output for leader judgement."""
    all_models = [s.model for s in element.specialists]

    def run_variant(args: tuple[int, LoadedSpecialist]) -> str:
        idx, specialist = args
        agent_id = f"{run_id}.{committee_name}.{element.id}.v{idx + 1}"
        return _run_one_specialist(
            specialist, element.skill_ids, task_brief, skills_map,
            committee_name, run_id, make_backend, agent_id,
        )

    with ThreadPoolExecutor(max_workers=len(element.specialists)) as pool:
        # pool.map preserves input order in its results.
        outputs = list(pool.map(run_variant, enumerate(element.specialists)))

    parts = [
        f"[{_variant_label(s, i, all_models)}]\n{output}"
        for i, (s, output) in enumerate(zip(element.specialists, outputs))
    ]
    return (
        "\n\n---\n\n".join(parts)
        + "\n\n[Select the variant that best meets the task objective, "
        "or synthesise across variants if complementary.]"
    )


def _run_element(
    element: LoadedElement,
    task_brief: str,
    skills_map: dict[str, LoadedSkill],
    committee_name: str,
    run_id: str,
    task_id: str,
    make_backend: BackendFactory,
) -> str:
    if len(element.specialists) == 1:
        # Single-specialist path: works for both combine and compare mode.
        (specialist,) = element.specialists
        agent_id = f"{run_id}.{committee_name}.{element.id}"
        return _run_one_specialist(
            specialist, element.skill_ids, task_brief, skills_map,
            committee_name, run_id, make_backend, agent_id,
        )

    if element.mode != "compare":
        raise NotImplementedError(
            f"Element {element.id!r}: mode='combine' with multiple specialists is not yet implemented"
        )

    return _run_compare(element, task_brief, skills_map, committee_name, run_id, make_backend)


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

    step_count = [0]
    _finished = [False]
    _incomplete = [False]
    _refuse_reason: list[str | None] = [None]

    def tool_dispatch(name: str, params: dict) -> str:
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
                output = _run_element(
                    element=element,
                    task_brief=task.brief,
                    skills_map=skills_map,
                    committee_name=committee.name,
                    run_id=run_id,
                    task_id=task_id,
                    make_backend=make_backend,
                )

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
            return f"Step {step_id} completed.\n\n{combined}"

        if name == "finish":
            _finished[0] = True
            return (
                f"Objective met. Synthesise your final committee artifact now.\n\n"
                f"Output only a valid JSON object matching the {schema_name} schema. "
                "No prose, no markdown fences, no extra keys."
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

    leader_tools = [
        _SUBMIT_STEP_TOOL, _FINISH_TOOL, _REFUSE_START_TOOL,
        _ASK_OPERATOR_TOOL, _REPLY_OPERATOR_TOOL,
    ]
    if committee.consumes_optional:
        leader_tools.append(_READ_ARTIFACT_TOOL)

    leader_id = f"{run_id}.{committee.name}.leader"
    pub.sendMessage(
        "agent.spawned",
        run_id=run_id,
        committee=committee.name,
        agent_id=leader_id,
        title="Committee Leader",
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

    raw = extract_json(artifact_text)
    try:
        artifact = committee.output_schema.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(
            f"Committee {committee.name!r} artifact failed schema validation: {exc}"
        ) from exc

    return artifact, _incomplete[0]
