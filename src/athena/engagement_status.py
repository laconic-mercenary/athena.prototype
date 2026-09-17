"""Engagement lifecycle constants.

Centralises string constants that describe:
- The run-status of an engagement (stored in EngagementContext.status).
- The await-phase of the pipeline (which operator decision is blocking it, if any).
- The in-loop gate kinds that a committee can arm or disarm at runtime.
"""

###############
# CONSTS / GLOBALS #
###############

# ---------------------------------------------------------------------------
# Engagement run status
# ---------------------------------------------------------------------------

# Created and waiting for a concurrency slot; not yet executing.
QUEUED = "queued"

# The engagement holds a concurrency slot and is actively executing.
RUNNING = "running"

# All committees completed successfully and the pipeline exited cleanly.
COMPLETED = "completed"

# The orchestrator or operator rejected the plan, or an in-pipeline rejection occurred.
REJECTED = "rejected"

# The pipeline raised an unhandled exception that terminated the worker thread.
FAILED = "failed"

# The operator pressed Restart / Abort while the engagement was in progress.
ABANDONED = "abandoned"

# All statuses that mean the engagement is over. Used by the SSE endpoint to
# synthesise a terminal event for clients that reconnect after the run finished
# (SSE has no replay; without this the client hangs on heartbeats indefinitely).
TERMINAL = frozenset({COMPLETED, REJECTED, FAILED, ABANDONED})


# ---------------------------------------------------------------------------
# Await phase
# Which operator decision, if any, is currently blocking the pipeline thread.
# Using distinct phase tokens (rather than a single bool) lets each route guard
# on its own phase — stale-tab POSTs to the wrong phase get a 409 instead of
# silently interfering with the active channel. See HARNESS_DEFICIENCIES.md H3.
# ---------------------------------------------------------------------------

# Not blocked; the pipeline is running freely.
AWAIT_NONE = "none"

# Blocked on the operator approving / rejecting / revising the briefing plan.
AWAIT_PLAN = "plan"

# Blocked on the operator's committee-gate decision (Accept / Redo) after a
# committee finishes at an operator_approval gate.
AWAIT_COMMITTEE_GATE = "committee_gate"

# Blocked on the operator's in-loop gate decision (element / step / tool).
AWAIT_LOOP_GATE = "loop_gate"


# ---------------------------------------------------------------------------
# Gate kinds (in-loop gates)
# ---------------------------------------------------------------------------

# The operator reviews and selects the winning specialist output for a compare element.
GATE_KIND_ELEMENT = "element"

# The operator reviews a completed step and decides whether to accept, redo, or skip.
GATE_KIND_STEP = "step"

# The operator authorises or denies a specialist's outbound tool call before it runs.
GATE_KIND_TOOL = "tool"

# Complete set of valid gate kinds — used for membership validation in route handlers.
GATE_KINDS = frozenset({GATE_KIND_ELEMENT, GATE_KIND_STEP, GATE_KIND_TOOL})


# ---------------------------------------------------------------------------
# Gate actions (in-loop gates)
# Valid actions differ PER KIND — an action string valid for one kind (e.g.
# "redo" for element/step) must not be accepted for another (e.g. tool, where
# it would silently fall through committee_runner._apply_tool_gate's
# deny-only check and approve a tool call nobody actually authorised). Route
# handlers must validate action against GATE_ACTIONS[kind] for whichever kind
# is actually pending (EngagementContext.loop_gate_kind), the same way they
# already validate kind itself against GATE_KINDS.
# ---------------------------------------------------------------------------

GATE_ACTION_ACCEPT = "accept"
GATE_ACTION_OVERRIDE = "override"
GATE_ACTION_REDO = "redo"
GATE_ACTION_SKIP = "skip"
GATE_ACTION_APPROVE = "approve"
GATE_ACTION_DENY = "deny"

# Complete set of valid actions per gate kind — used for membership validation
# in route handlers, keyed by whichever kind is actually pending.
GATE_ACTIONS: dict[str, frozenset[str]] = {
    GATE_KIND_ELEMENT: frozenset({GATE_ACTION_ACCEPT, GATE_ACTION_OVERRIDE, GATE_ACTION_REDO}),
    GATE_KIND_STEP: frozenset({GATE_ACTION_ACCEPT, GATE_ACTION_REDO, GATE_ACTION_SKIP}),
    GATE_KIND_TOOL: frozenset({GATE_ACTION_APPROVE, GATE_ACTION_DENY}),
}
