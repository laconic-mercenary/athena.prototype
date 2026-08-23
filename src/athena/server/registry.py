"""In-memory engagement registry.

Tracks live engagements by run_id, each tagged with the project it belongs to (via
Engagement.project_name). Project metadata and durability live in projects_store; this
registry holds only the running engagements, which are ephemeral by design.
"""

from typing import TYPE_CHECKING

from athena import engagement_status

if TYPE_CHECKING:
    from athena.server.runner import Engagement, EngagementContext


###############
# CONSTS / GLOBALS #
###############


###############
# CUSTOM TYPES #
###############


###############
# CLASSES #
###############

class Registry:
    """Holds live engagements keyed by run_id and resolves lookups across them."""

    def __init__(self) -> None:
        self._engagements: dict[str, "Engagement"] = {}

    def add_engagement(self, engagement: "Engagement") -> None:
        self._engagements[engagement.run_id] = engagement

    def remove_engagement(self, run_id: str) -> None:
        self._engagements.pop(run_id, None)

    def get_engagement(self, run_id: str) -> "Engagement | None":
        return self._engagements.get(run_id)

    def get_context(self, run_id: str) -> "EngagementContext | None":
        engagement = self._engagements.get(run_id)
        return engagement.context if engagement is not None else None

    def engagements_for_project(self, project_name: str) -> list["Engagement"]:
        return [e for e in self._engagements.values() if e.project_name == project_name]

    def is_busy(self) -> bool:
        return any(
            e.context.status == engagement_status.RUNNING for e in self._engagements.values()
        )


###############
# FUNCTIONS #
###############


###############
# NON PUBLIC FUNCTIONS #
###############
