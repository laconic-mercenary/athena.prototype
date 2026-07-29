"""Workflow driver — traverses the ensemble's committee graph.

Responsibilities:
- Runs committees in order, starting from the entry node
- Calls the orchestrator for a gate decision after each committee
- Follows advance / retry / iterate decisions
- Enforces operator_approval gates (blocks until the operator acts)
- Tracks global step budget and retry/iterate counts
- Writes artifacts to disk after each committee run

The workflow driver does NOT know about any specific ensemble — it operates
on the graph declared in the LoadedEnsemble manifest.
"""

from __future__ import annotations

import logging
import queue
from pathlib import Path
from typing import Callable

from pubsub import pub
from pydantic import BaseModel

from athena.engagement_plan import CommitteeBrief, EngagementPlan
from athena.ensemble.types import LoadedEnsemble, WorkflowNode
from athena.harness.committee_runner import RefuseStartError, run_committee_with_ensemble
from athena.harness.orchestrator import GateDecision, OrchestratorHarness
from athena.model_backend import ModelBackend

_log = logging.getLogger("athena.harness.workflow")

GLOBAL_STEP_BUDGET = 750

BackendFactory = Callable[[str, "str | None"], ModelBackend]
AskOperatorHandler = Callable[[str], str]
ApprovalHandler = Callable[[], bool]


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _is_terminal(node: WorkflowNode) -> bool:
    """A committee is terminal iff it has no forward (non-retry/iterate) transitions."""
    return not any(
        t.condition not in ("retry", "iterate") for t in node.transitions
    )


def _forward_target(node: WorkflowNode) -> str | None:
    """Return the to-committee for the unconditional (advance) transition, if any."""
    for t in node.transitions:
        if t.condition is None:
            return t.to
    return None


def _has_declared_transition(node: WorkflowNode, condition: str, to: str) -> bool:
    return any(t.condition == condition and t.to == to for t in node.transitions)


# ---------------------------------------------------------------------------
# Main workflow runner
# ---------------------------------------------------------------------------

def run_workflow(
    ensemble: LoadedEnsemble,
    plan: EngagementPlan,
    orchestrator: OrchestratorHarness,
    make_backend: BackendFactory,
    artifacts_dir: Path,
    run_id: str,
    ask_operator_handler: AskOperatorHandler,
    approval_handler: ApprovalHandler,
    leader_queues: dict[str, queue.Queue],
    global_step_budget: int,
) -> None:
    """Traverse the workflow graph until a terminal committee advances."""

    artifacts_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, BaseModel] = {}
    retry_counts: dict[str, int] = {}
    iterate_counts: dict[str, int] = {}
    current = ensemble.entry

    while current:
        node = ensemble.workflow[current]
        committee = ensemble.committees[current]

        brief = plan.committees.get(
            current, CommitteeBrief(objective=[f"Complete the {current} committee task."])
        )
        prior_artifact = artifacts.get(current)
        is_retry = retry_counts.get(current, 0) > 0 and prior_artifact is None
        is_iterate = iterate_counts.get(current, 0) > 0 and prior_artifact is not None

        pub.sendMessage(
            "committee.started",
            run_id=run_id,
            committee=current,
            objective=brief.objective,
        )

        try:
            artifact, incomplete = run_committee_with_ensemble(
                ensemble=ensemble,
                committee_name=current,
                brief=brief,
                prior_artifacts=artifacts,
                artifacts_dir=artifacts_dir,
                run_id=run_id,
                make_backend=make_backend,
                ask_operator_handler=ask_operator_handler,
                operator_queue=leader_queues.get(current),
                is_retry=is_retry,
                is_iterate=is_iterate,
                prior_artifact=prior_artifact if is_iterate else None,
            )
        except RefuseStartError as exc:
            _log.error("Committee %r refused to start: %s", current, exc.reason)
            pub.sendMessage(
                "engagement.rejected",
                run_id=run_id,
                reason=f"Committee {current!r} refused: {exc.reason}",
            )
            return

        # Persist artifact to disk
        artifact_path = artifacts_dir / f"{current}.json"
        artifact_path.write_text(artifact.model_dump_json())
        artifacts[current] = artifact

        digest = artifact.render_digest() if hasattr(artifact, "render_digest") else artifact.model_dump_json()

        pub.sendMessage(
            "committee.completed",
            run_id=run_id,
            committee=current,
            digest=digest,
            incomplete=incomplete,
            artifact=str(artifact_path),
        )

        # Check for operator_approval gate after this committee
        gate = next((g for g in plan.gates if g.after == current), None)
        if gate is not None:
            # Tell the orchestrator where we are before it can receive operator
            # messages — otherwise it only has briefing context and will give
            # wrong answers about what has run.
            orchestrator.inject_harness_update(
                f"== Operator-approval gate: {current!r} complete ==\n"
                f"The {current!r} committee has just finished. The engagement is now "
                f"paused at an operator-approval gate. The operator is reviewing the "
                f"output in the UI and will approve (continue to the next committee) "
                f"or reject (end the engagement). No other committees are running.\n"
                f"If the operator messages you, answer accurately based on what has "
                f"been completed so far. Do not say the pipeline is starting or that "
                f"committees are running — everything is paused until they approve."
            )
            pub.sendMessage("gate.awaiting_approval", run_id=run_id, committee=current)
            approved = approval_handler()
            if not approved:
                pub.sendMessage(
                    "engagement.rejected",
                    run_id=run_id,
                    reason=f"Operator rejected at gate after {current!r}",
                )
                return
            pub.sendMessage("engagement.approved", run_id=run_id)

        terminal = _is_terminal(node)

        decision = orchestrator.run_gate(
            committee_name=current,
            digest=digest,
            gate_type=gate.type.value if gate else "auto",
            retry_count=retry_counts.get(current, 0),
            iterate_count=iterate_counts.get(current, 0),
        )

        _log.info("Gate %r → %s (rationale: %s)", current, decision.decision, decision.rationale)

        if decision.decision == "advance":
            if terminal:
                pub.sendMessage("engagement.completed", run_id=run_id)
                return

            next_committee = _forward_target(node)
            if next_committee is None:
                _log.error("advance called on %r but no forward transition found", current)
                pub.sendMessage("engagement.completed", run_id=run_id)
                return

            # Refine the next committee's objective if the orchestrator provided one
            if decision.next_objective and next_committee in plan.committees:
                plan.committees[next_committee].objective.insert(0, decision.next_objective)

            # Clear the prior artifact for the next committee (fresh start)
            artifacts.pop(next_committee, None)
            retry_counts.pop(next_committee, None)
            iterate_counts.pop(next_committee, None)
            current = next_committee

        elif decision.decision == "retry":
            to = decision.to or current
            if not _has_declared_transition(node, "retry", to):
                _log.warning(
                    "Orchestrator called retry(%r) on %r but that transition is not declared. "
                    "Defaulting to advance.",
                    to, current,
                )
                decision.decision = "advance"
                current = _forward_target(node) or current
                continue

            retry_counts[to] = retry_counts.get(to, 0) + 1
            if decision.note and to in plan.committees:
                plan.committees[to].objective.append(decision.note)

            # Fresh start: clear prior artifact so retry doesn't see old output
            artifacts.pop(to, None)

            if to != current:
                # Back-edge: also clear everything between to and current
                _clear_downstream(to, current, ensemble, artifacts, retry_counts, iterate_counts)

            current = to

        elif decision.decision == "iterate":
            to = decision.to or current
            if not _has_declared_transition(node, "iterate", to):
                _log.warning(
                    "Orchestrator called iterate(%r) on %r but that transition is not declared. "
                    "Defaulting to advance.",
                    to, current,
                )
                decision.decision = "advance"
                current = _forward_target(node) or current
                continue

            iterate_counts[to] = iterate_counts.get(to, 0) + 1
            if decision.note and to in plan.committees:
                plan.committees[to].objective.append(decision.note)

            # For iterate, the prior artifact IS shown — leave it in artifacts[to]

            if to != current:
                _clear_downstream(to, current, ensemble, artifacts, retry_counts, iterate_counts)

            current = to

        else:
            # Should not happen (ask_operator is resolved inside orchestrator.run_gate)
            _log.error("Unexpected gate decision %r", decision.decision)
            current = _forward_target(node) or current


def _clear_downstream(
    from_committee: str,
    to_committee: str,
    ensemble: LoadedEnsemble,
    artifacts: dict,
    retry_counts: dict,
    iterate_counts: dict,
) -> None:
    """Clear artifacts and counts for committees between from_committee and to_committee
    (exclusive of from_committee, inclusive of to_committee) when a back-edge fires."""
    # Walk the forward graph from from_committee until we reach to_committee
    visited: set[str] = set()
    node_name = _forward_target(ensemble.workflow.get(from_committee, None))
    while node_name and node_name != to_committee and node_name not in visited:
        visited.add(node_name)
        artifacts.pop(node_name, None)
        retry_counts.pop(node_name, None)
        iterate_counts.pop(node_name, None)
        next_node = ensemble.workflow.get(node_name)
        node_name = _forward_target(next_node) if next_node else None
