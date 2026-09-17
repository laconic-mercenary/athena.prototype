"""Per-engagement progress snapshots for late-joining SSE clients and projects-view rows.

An SSE stream is live-only — events fire once, with no replay — so a row needs a way to
render an engagement's current state before it connects, and to recover it on reconnect.
This module subscribes to the pipeline's pubsub events and keeps a small derived snapshot
per run_id (current committee, active specialist, which committees have completed) that the
progress route serves over a plain GET. Authoritative status and gate-awaiting come from the
EngagementContext, not from here.
"""

from dataclasses import dataclass, field
from typing import NamedTuple

from pubsub import pub

from athena import topics


###############
# CONSTS / GLOBALS #
###############

# Keyed by run_id. Written on the harness thread (pubsub), read on the event-loop thread
# (the route). Single field writes and set.add are atomic under the GIL, and the route only
# ever reads — matching the lock-free discipline in bus.py.
_snapshots: dict[str, "_Progress"] = {}


###############
# CUSTOM TYPES #
###############

@dataclass
class _Progress:
    current_committee: str | None = None
    active_specialist: str | None = None
    completed: set[str] = field(default_factory=set)


class Snapshot(NamedTuple):
    current_committee: str | None
    active_specialist: str | None
    completed_committees: int


###############
# FUNCTIONS #
###############

def snapshot(run_id: str) -> Snapshot:
    """Derived progress for a run: current committee, active specialist, and the count of
    distinct committees that have completed. Empty defaults when nothing has been seen yet."""
    snap = _snapshots.get(run_id)
    if snap is None:
        return Snapshot(None, None, 0)
    return Snapshot(
        current_committee=snap.current_committee,
        active_specialist=snap.active_specialist,
        completed_committees=len(snap.completed),
    )


###############
# NON PUBLIC FUNCTIONS #
###############

def _on_event(topicObj=pub.AUTO_TOPIC, **kwargs) -> None:
    run_id = kwargs.get("run_id")
    if not run_id:
        return
    topic = topicObj.getName()
    if topic == topics.COMMITTEE_STARTED:
        _snapshots.setdefault(run_id, _Progress()).current_committee = kwargs.get("committee")
    elif topic == topics.COMMITTEE_COMPLETED:
        _snapshots.setdefault(run_id, _Progress()).completed.add(kwargs.get("committee"))
    elif topic == topics.AGENT_SPAWNED:
        _snapshots.setdefault(run_id, _Progress()).active_specialist = kwargs.get("title")


pub.subscribe(_on_event, pub.ALL_TOPICS)
