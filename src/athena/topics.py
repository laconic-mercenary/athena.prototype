"""PyPubSub topic constants for all pipeline SSE signals.

Every pub.sendMessage() call and every subscriber (including the SSE bridge
in bus.py) must reference topics from this module — never bare string literals.

Each constant's comment documents what the event signals, when it fires, and
which keyword arguments it carries (run_id is always present).
"""

###############
# CONSTS / GLOBALS #
###############

# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------

# An agent (leader or specialist) has started.
# Fires at the beginning of every run_agent() call, before the first model turn.
# kwargs: run_id, committee, agent_id, title, role
#   Specialist-only extras: element_id, element_label, variant_label
AGENT_SPAWNED = "agent.spawned"

# An agent finished its run cleanly (end_turn reached or iteration cap hit).
# kwargs: run_id, committee, agent_id
AGENT_SPUN_DOWN = "agent.spun_down"

# A compare-mode specialist raised an unhandled exception and was dropped as a
# variant. The element continues with remaining survivors.
# kwargs: run_id, committee, agent_id, error
AGENT_FAILED = "agent.failed"

# ---------------------------------------------------------------------------
# Agent turn events
# ---------------------------------------------------------------------------

# The model produced a text response or a stop-reason event during a turn.
# kwargs: run_id, committee, agent_id, text, stop_reason
AGENT_MODEL_TEXT = "agent.model_text"

# A tool call was received from the model and is about to be dispatched.
# kwargs: run_id, committee, agent_id, tool, call_id, input_summary
AGENT_TOOL_CALLED = "agent.tool_called"

# The tool dispatch returned a result for the most recent tool call.
# kwargs: run_id, committee, agent_id, tool, call_id, result
AGENT_TOOL_RESULT = "agent.tool_result"

# A leader sent an explicit reply to the operator via the reply_operator tool,
# without advancing its planning work.
# kwargs: run_id, committee, agent_id, text
AGENT_OPERATOR_REPLY = "agent.operator_reply"

# ---------------------------------------------------------------------------
# Committee lifecycle
# ---------------------------------------------------------------------------

# A committee's run_committee_with_ensemble() call has started.
# kwargs: run_id, committee
COMMITTEE_STARTED = "committee.started"

# A committee finished and produced its typed artifact.
# kwargs: run_id, committee
COMMITTEE_COMPLETED = "committee.completed"

# A committee artifact was written to disk and is available for download.
# kwargs: run_id, committee, artifact_path
COMMITTEE_ARTIFACT_EMITTED = "committee.artifact_emitted"

# The leader selected a winner from a compare-mode element's variants.
# kwargs: run_id, committee, element_id, winner_id, winner_title, rationale, result, variants
COMMITTEE_RESULT_SELECTED = "committee.result_selected"

# The leader paused work and surfaced a question to the operator via ask_operator.
# kwargs: run_id, committee, question
COMMITTEE_ASK_OPERATOR = "committee.ask_operator"

# The operator replied to a committee leader's ask_operator question.
# kwargs: run_id, committee
COMMITTEE_OPERATOR_REPLIED = "committee.operator_replied"

# ---------------------------------------------------------------------------
# Step / task lifecycle
# ---------------------------------------------------------------------------

# A leader submitted a new step for execution via the submit_step tool.
# kwargs: run_id, committee, step_id, description, tasks
STEP_STARTED = "step.started"

# All tasks in a step have finished executing.
# kwargs: run_id, committee, step_id
STEP_COMPLETED = "step.completed"

# A step's output was superseded by a later step (leader called submit_step with
# a supersedes list referencing this step's ID).
# kwargs: run_id, committee, step_id
STEP_SUPERSEDED = "step.superseded"

# A single task within a step started executing (one element of the step).
# kwargs: run_id, committee, step_id, task_id, element, brief
TASK_STARTED = "task.started"

# A single task within a step finished executing.
# kwargs: run_id, committee, step_id, task_id, summary
TASK_COMPLETED = "task.completed"

# ---------------------------------------------------------------------------
# Engagement lifecycle
# ---------------------------------------------------------------------------

# A new engagement has been started and the briefing phase is underway.
# kwargs: run_id, ensemble, version
ENGAGEMENT_STARTED = "engagement.started"

# The engagement completed all committees successfully.
# kwargs: run_id
ENGAGEMENT_COMPLETED = "engagement.completed"

# The engagement was rejected — either the orchestrator refused the plan, the
# operator declined during plan review, or an unrecoverable pipeline error occurred.
# kwargs: run_id, reason
ENGAGEMENT_REJECTED = "engagement.rejected"

# The operator aborted a running engagement (demo Restart / Abandon).
# kwargs: run_id
ENGAGEMENT_ABORTED = "engagement.aborted"

# The operator approved the briefing plan and pipeline execution is starting.
# kwargs: run_id
ENGAGEMENT_APPROVED = "engagement.approved"

# The orchestrator produced its first briefing plan and it is ready for operator review.
# kwargs: run_id
ENGAGEMENT_PLAN_READY = "engagement.plan_ready"

# The operator requested a plan revision and the orchestrator is being re-prompted.
# kwargs: run_id
ENGAGEMENT_PLAN_REVISION = "engagement.plan_revision"

# A co-approval email has been sent to a collaborator; the gate is parked until
# the collaborator replies.
# kwargs: run_id, alias, sent_at
ENGAGEMENT_COLLABORATOR_PENDING = "engagement.collaborator_pending"

# ---------------------------------------------------------------------------
# Gate events
# ---------------------------------------------------------------------------

# The pipeline is blocked at a committee gate awaiting the operator's decision
# (Accept / Redo). The gate stays parked until gate-decision is POSTed.
# kwargs: run_id, committee, digest, redo_available
GATE_AWAITING_APPROVAL = "gate.awaiting_approval"

# The operator's gate decision has been recorded and the gate released.
# kwargs: run_id, action
GATE_DECISION = "gate.decision"

# The operator selected Redo at a gate that does not support it (reserved for
# future gate kinds that are forward-only).
# kwargs: run_id
GATE_REDO_UNSUPPORTED = "gate.redo_unsupported"

# The pipeline is blocked at an in-loop gate awaiting the operator's decision on
# a tool call, a completed step, or an element selection.
# kwargs: run_id, kind, committee, payload
LOOP_GATE_AWAITING = "loop_gate.awaiting"

# An in-loop gate has been resolved and the pipeline is continuing.
# kwargs: run_id, kind, committee, action
LOOP_GATE_RESOLVED = "loop_gate.resolved"

# ---------------------------------------------------------------------------
# Orchestrator chat
# ---------------------------------------------------------------------------

# The orchestrator sent a freeform message to the operator outside of a
# structured question/answer exchange.
# kwargs: run_id, message
ORCHESTRATOR_MESSAGE = "orchestrator.message"

# The orchestrator paused its turn to ask the operator a direct question
# (via the ask_user tool or equivalent).
# kwargs: run_id, question
ORCHESTRATOR_QUESTION = "orchestrator.question"

# The operator replied to an orchestrator question.
# kwargs: run_id, answer
ORCHESTRATOR_ANSWER = "orchestrator.answer"

# ---------------------------------------------------------------------------
# Collaboration
# ---------------------------------------------------------------------------

# The collaborator replied to a co-approval email. decision is "approve", "deny",
# or "comment" (a reply with no clear keyword — leaves the gate parked so the
# operator can keep the thread going).
# kwargs: run_id, alias, kind, committee, decision, message
COLLABORATOR_REPLIED = "collaborator.replied"

# The operator sent a follow-up message into the collaborator's email thread
# while the co-approval gate is parked.
# kwargs: run_id, alias, committee, message
COLLABORATOR_OPERATOR_MESSAGE = "collaborator.operator_message"
