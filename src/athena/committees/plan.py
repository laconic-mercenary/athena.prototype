"""Intra-committee execution plan types.

CommitteeStep and CommitteeTask are the leader's just-in-time planning
primitives. The leader emits one Step at a time via submit_step(); the
harness stamps a UUID id and executes the Tasks sequentially.
"""

from pydantic import BaseModel


###############
# CUSTOM TYPES #
###############

class CommitteeTask(BaseModel):
    """One task within a committee step — an element ID paired with the leader's brief.

    Produced by the committee leader inside each submit_step() call. The harness
    dispatches the task to the named element's specialist(s) and returns their
    outputs to the leader before the next step may be submitted.
    """

    element: str   # element id declared for this committee in the manifest
    brief:   str   # leader-written assignment


class CommitteeStep(BaseModel):
    """One iteration of work within a committee run, containing one or more tasks.

    The leader emits steps one at a time via submit_step(). The harness stamps a UUID,
    executes all tasks within the step sequentially, then returns results to the leader.
    A step may supersede earlier steps when the leader revises its plan mid-run.
    """

    id:          str                    # harness-assigned UUID
    description: str
    tasks:       list[CommitteeTask]
    supersedes:  list[str] = []         # ids of prior Steps this Step replaces
