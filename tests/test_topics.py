"""Tests for athena.topics constants."""

import athena.topics as topics


_ALL_TOPIC_NAMES = [
    "AGENT_SPAWNED", "AGENT_SPUN_DOWN", "AGENT_FAILED",
    "AGENT_MODEL_TEXT", "AGENT_TOOL_CALLED", "AGENT_TOOL_RESULT", "AGENT_OPERATOR_REPLY",
    "COMMITTEE_STARTED", "COMMITTEE_COMPLETED", "COMMITTEE_ARTIFACT_EMITTED",
    "COMMITTEE_RESULT_SELECTED", "COMMITTEE_ASK_OPERATOR", "COMMITTEE_OPERATOR_REPLIED",
    "STEP_STARTED", "STEP_COMPLETED", "STEP_SUPERSEDED",
    "TASK_STARTED", "TASK_COMPLETED",
    "ENGAGEMENT_STARTED", "ENGAGEMENT_COMPLETED", "ENGAGEMENT_REJECTED",
    "ENGAGEMENT_ABORTED", "ENGAGEMENT_APPROVED", "ENGAGEMENT_PLAN_READY",
    "ENGAGEMENT_PLAN_REVISION", "ENGAGEMENT_COLLABORATOR_PENDING",
    "GATE_AWAITING_APPROVAL", "GATE_DECISION", "GATE_REDO_UNSUPPORTED",
    "LOOP_GATE_AWAITING", "LOOP_GATE_RESOLVED",
    "ORCHESTRATOR_MESSAGE", "ORCHESTRATOR_QUESTION", "ORCHESTRATOR_ANSWER",
    "COLLABORATOR_REPLIED", "COLLABORATOR_OPERATOR_MESSAGE",
]


def test_all_topic_constants_exist() -> None:
    for name in _ALL_TOPIC_NAMES:
        assert hasattr(topics, name), f"topics.{name} is missing"


def test_all_topic_values_are_non_empty_strings() -> None:
    for name in _ALL_TOPIC_NAMES:
        val = getattr(topics, name)
        assert isinstance(val, str) and val, f"topics.{name} must be a non-empty string"


def test_all_topic_values_are_unique() -> None:
    values = [getattr(topics, n) for n in _ALL_TOPIC_NAMES]
    assert len(values) == len(set(values)), "Duplicate topic string values detected"


def test_topic_naming_convention() -> None:
    # All topic strings must use dot-separated lowercase segments (underscores within
    # a segment are allowed, e.g. "agent.spun_down").
    for name in _ALL_TOPIC_NAMES:
        val = getattr(topics, name)
        segments = val.split(".")
        assert len(segments) >= 2, f"topics.{name}={val!r} must have at least two dot-separated segments"
        for seg in segments:
            assert seg, f"topics.{name}={val!r} has an empty segment"
            assert seg == seg.lower(), f"topics.{name}={val!r} has an uppercase character in segment {seg!r}"


def test_total_topic_count() -> None:
    assert len(_ALL_TOPIC_NAMES) == 36
