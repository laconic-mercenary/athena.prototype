"""Tests for harness/skill_executor.py."""

import json

import pytest

from athena.ensemble.types import LoadedSkill
from athena.harness.skill_executor import execute_skill, skill_to_tool_def
from athena.model_backend import ToolDefinition


def _skill(name: str = "test_skill", impl=None) -> LoadedSkill:
    if impl is None:
        impl = lambda **kw: {"ok": True}  # noqa: E731
    return LoadedSkill(
        id="test_id",
        name=name,
        description="A test skill",
        parameters={
            "type": "object",
            "properties": {"arg": {"type": "string"}},
            "required": ["arg"],
        },
        impl=impl,
    )


# ---------------------------------------------------------------------------
# skill_to_tool_def
# ---------------------------------------------------------------------------

def test_skill_to_tool_def_returns_tool_definition():
    skill = _skill("my_skill")
    td = skill_to_tool_def(skill)
    assert isinstance(td, ToolDefinition)
    assert td.name == "my_skill"
    assert td.description == "A test skill"
    assert td.parameters == skill.parameters


def test_skill_to_tool_def_preserves_parameters():
    skill = _skill()
    td = skill_to_tool_def(skill)
    assert "properties" in td.parameters
    assert "arg" in td.parameters["properties"]


# ---------------------------------------------------------------------------
# execute_skill
# ---------------------------------------------------------------------------

def test_execute_skill_returns_json_string():
    skill = _skill(impl=lambda **kw: {"result": "value"})
    result = execute_skill(skill, {"arg": "hello"})
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed == {"result": "value"}


def test_execute_skill_passes_kwargs():
    received = {}

    def impl(**kw):
        received.update(kw)
        return {}

    skill = _skill(impl=impl)
    execute_skill(skill, {"arg": "test", "extra": 42})
    assert received["arg"] == "test"
    assert received["extra"] == 42


def test_execute_skill_propagates_exception():
    def impl(**kw):
        raise ValueError("bad input")

    skill = _skill(impl=impl)
    with pytest.raises(ValueError, match="bad input"):
        execute_skill(skill, {})
