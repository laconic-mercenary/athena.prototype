"""PendingDecision — the typed, code-first counterpart to the HTTP gate routes.

Engagement.wait_for_decision() returns one of these subtypes (or None once the
engagement is terminal). Each subtype exposes exactly the actions valid for that
gate kind — there is no shared "action: str" parameter to get wrong, so calling
.override() on a StepGateDecision is an AttributeError, not a silently-ignored
mismatch. Every instance is an immutable snapshot (its fields are copied at
construction, not live references into EngagementContext) and single-use: acting
on it a second time raises, instead of the pre-existing free-function path's
un-guarded re-arm of a threading.Event.

This is deliberately a second, additive path onto the same underlying Engagement
methods (resolve_approval, resolve_gate_decision, resolve_loop_gate_decision) that
the HTTP routes already call directly. Resolving a gate via HTTP while a
PendingDecision for it is still held elsewhere is not guarded against here — full
cross-interface exclusivity is out of scope until the HTTP routes themselves become
an adapter over this same object (see the harness's stated direction for that work).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from athena import engagement_status

if TYPE_CHECKING:
    from athena.engagement_plan import EngagementPlan
    from athena.server.runner import Engagement


###############
# CLASSES #
###############

class PendingDecision:
    """Base for whatever this engagement needs from the operator right now."""

    def __init__(self, engagement: "Engagement") -> None:
        self._engagement = engagement
        self._resolved = False

    def _resolve_once(self, action) -> None:
        """Guard against acting on this decision twice. Clearing the engagement's
        current-pending-decision pointer happens under the same lock as the
        already-resolved check, so a caller that immediately loops back into
        wait_for_decision() can never observe this (now-stale) object again —
        it either blocks for the next decision or sees the next one already posted.
        """
        cv = self._engagement._decision_cv
        with cv:
            if self._resolved:
                raise RuntimeError(f"{type(self).__name__} was already resolved")
            self._resolved = True
            if self._engagement._pending_decision is self:
                self._engagement._pending_decision = None
            cv.notify_all()
        action()


class OrchestratorQuestion(PendingDecision):
    """The orchestrator needs clarification before it can propose a plan (the
    pre-plan briefing dialogue — distinct from the plan-approval gate below, and
    from an operator-approval-gate freeform message; see chat.py's routing, which
    this does not change: it still keys off pending_question/awaiting_approval on
    EngagementContext, not a dedicated AWAIT_* phase)."""

    def __init__(self, engagement: "Engagement", question: str) -> None:
        super().__init__(engagement)
        self.question = question

    def answer(self, text: str) -> None:
        self._resolve_once(lambda: self._engagement.reply_to_orchestrator(text))


class PlanApproval(PendingDecision):
    """The orchestrator's proposed plan is awaiting operator approval, revision, or
    rejection."""

    def __init__(self, engagement: "Engagement", plan: "EngagementPlan") -> None:
        super().__init__(engagement)
        self.plan = plan

    def approve(self) -> None:
        self._resolve_once(lambda: self._engagement.resolve_approval(approved=True))

    def reject(self) -> None:
        self._resolve_once(lambda: self._engagement.resolve_approval(approved=False))

    def request_revision(self, message: str) -> None:
        self._resolve_once(lambda: self._engagement.request_revision(message))


class CommitteeGateDecision(PendingDecision):
    """A committee finished at an operator_approval gate; the operator decides
    whether to advance or redo it."""

    def __init__(
        self, engagement: "Engagement", *, committee: str, digest: str, redo_available: bool
    ) -> None:
        super().__init__(engagement)
        self.committee = committee
        self.digest = digest
        self.redo_available = redo_available

    def accept(self) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_gate_decision(action="accept", suggestion=None)
        )

    def redo(self, suggestion: str | None = None) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_gate_decision(action="redo", suggestion=suggestion)
        )


class ElementGateDecision(PendingDecision):
    """A compare-mode element selected a winner; the operator confirms it, overrides
    it, or sends the leader back to re-select."""

    def __init__(
        self,
        engagement: "Engagement",
        *,
        committee: str,
        element_id: str,
        winner_id: str,
        rationale: str,
        variants: list[dict[str, Any]],
    ) -> None:
        super().__init__(engagement)
        self.committee = committee
        self.element_id = element_id
        self.winner_id = winner_id
        self.rationale = rationale
        self.variants = variants  # each: {"label": str, "title": str, "output": str}

    def accept(self) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="accept")
        )

    def override(self, winner_id: str) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(
                action="override", payload={"winner_id": winner_id}
            )
        )

    def redo(self) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="redo")
        )


class StepGateDecision(PendingDecision):
    """A step finished; the operator accepts it, sends it back with a note, or skips
    review and moves on."""

    def __init__(
        self, engagement: "Engagement", *, committee: str, step_id: str, description: str, digest: str
    ) -> None:
        super().__init__(engagement)
        self.committee = committee
        self.step_id = step_id
        self.description = description
        self.digest = digest

    def accept(self) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="accept")
        )

    def redo(self, suggestion: str | None = None) -> None:
        payload = {"suggestion": suggestion} if suggestion else None
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="redo", payload=payload)
        )

    def skip(self) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="skip")
        )


class ToolGateDecision(PendingDecision):
    """A specialist wants to call a domain tool; the operator authorizes or denies it
    before it runs."""

    def __init__(
        self, engagement: "Engagement", *, committee: str, tool: str, args: dict, side_effect: str
    ) -> None:
        super().__init__(engagement)
        self.committee = committee
        self.tool = tool
        self.args = args
        self.side_effect = side_effect  # "reads_local" | "touches_target"

    def approve(self) -> None:
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="approve")
        )

    def deny(self, reason: str | None = None) -> None:
        payload = {"reason": reason} if reason else None
        self._resolve_once(
            lambda: self._engagement.resolve_loop_gate_decision(action="deny", payload=payload)
        )


###############
# FUNCTIONS #
###############

def build_loop_gate_decision(
    engagement: "Engagement", kind: str, committee: str, payload: dict
) -> PendingDecision:
    """Construct the PendingDecision subtype matching an in-loop gate's kind."""
    if kind == engagement_status.GATE_KIND_ELEMENT:
        return ElementGateDecision(
            engagement,
            committee=committee,
            element_id=payload.get("element_id", ""),
            winner_id=payload.get("winner_id", ""),
            rationale=payload.get("rationale", ""),
            variants=payload.get("variants", []),
        )
    if kind == engagement_status.GATE_KIND_STEP:
        return StepGateDecision(
            engagement,
            committee=committee,
            step_id=payload.get("step_id", ""),
            description=payload.get("description", ""),
            digest=payload.get("digest", ""),
        )
    if kind == engagement_status.GATE_KIND_TOOL:
        return ToolGateDecision(
            engagement,
            committee=committee,
            tool=payload.get("tool", ""),
            args=payload.get("args", {}),
            side_effect=payload.get("side_effect", ""),
        )
    raise ValueError(f"Unknown loop gate kind: {kind!r}")
