"""Harness-side types for a loaded ensemble.

These are the resolved, in-memory representations of the manifest — all file
references followed, all imports resolved, all schemas imported. Nothing here
touches the LLM; it is pure load-time structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Type

from pydantic import BaseModel


@dataclass
class LoadedSkill:
    id:          str
    name:        str
    description: str
    parameters:  dict          # JSON Schema object (for ToolDefinition)
    impl:        Callable[..., Any]


@dataclass
class LoadedSpecialist:
    id:          str              # yml filename stem (e.g. "counter")
    system:      str
    model:       str
    provider:    str              # "anthropic" | "ollama"
    temperature: float | None     # None → provider default; set for sampling diversity


@dataclass
class LoadedElement:
    id:          str
    instances:   int
    specialists: list[LoadedSpecialist]
    skill_ids:   list[str]        # references into LoadedEnsemble.skills
    mode:        str              # "combine" (single) | "compare" (best-of-N)


@dataclass
class LoadedCommittee:
    name:             str
    leader_system:    str
    model:            str
    provider:         str
    max_steps:        int
    playbook:         str
    elements:         list[LoadedElement]
    task_cards:       dict[str, str]       # element_id → task.md text
    output_schema:    Type[BaseModel]
    consumes_required: list[str]
    consumes_optional: list[str]


@dataclass
class WorkflowTransition:
    to:        str
    condition: str | None   # None = forward advance; "retry" | "iterate" | "operator_approval"


@dataclass
class WorkflowNode:
    name:        str
    transitions: list[WorkflowTransition]
    output_schema: Type[BaseModel]


@dataclass
class LoadedEnsemble:
    name:        str
    version:     str
    description: str
    capability:  str                         # content of capability.md
    entry:       str                         # entry committee name
    workflow:    dict[str, WorkflowNode]     # committee_name → WorkflowNode
    committees:  dict[str, LoadedCommittee]
    skills:      dict[str, LoadedSkill]      # skill_id → LoadedSkill
    root:        Path
