"""Intra-committee execution plan types.

CommitteeStep and CommitteeTask are the leader's just-in-time planning
primitives. The leader emits one Step at a time via submit_step(); the
harness stamps a UUID id and executes the Tasks sequentially.
"""

from pydantic import BaseModel


class CommitteeTask(BaseModel):
    element: str   # element id declared for this committee in the manifest
    brief:   str   # leader-written assignment


class CommitteeStep(BaseModel):
    id:          str                    # harness-assigned UUID
    description: str
    tasks:       list[CommitteeTask]
    supersedes:  list[str] = []         # ids of prior Steps this Step replaces
