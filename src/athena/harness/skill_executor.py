"""Skill execution — call a LoadedSkill's impl and return a JSON result string."""

from __future__ import annotations

import json

from athena.ensemble.types import LoadedSkill
from athena.model_backend import ToolDefinition


###############
# FUNCTIONS #
###############

def skill_to_tool_def(skill: LoadedSkill) -> ToolDefinition:
    """Convert a LoadedSkill to a ToolDefinition the agent loop can use."""
    return ToolDefinition(
        name=skill.name,
        description=skill.description,
        parameters=skill.parameters,
    )


def execute_skill(skill: LoadedSkill, params: dict) -> str:
    """Call the skill's Python impl with params and return the result as JSON."""
    result = skill.impl(**params)
    return json.dumps(result)
