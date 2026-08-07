"""Tests for athena.server.limits validation constants."""

from athena.server import limits


def test_all_constants_are_positive_integers() -> None:
    for name in ("MAX_MESSAGE_LEN", "MAX_SUGGESTION_LEN", "MAX_INSTRUCTIONS_LEN",
                 "MAX_KEY_LEN", "MAX_ID_LEN"):
        val = getattr(limits, name)
        assert isinstance(val, int) and val > 0, f"{name} must be a positive integer"


def test_max_message_len_equals_2000() -> None:
    # 2 000 chars chosen to cover multi-sentence operator instructions without bloating
    # the model context — documented in server/limits.py.
    assert limits.MAX_MESSAGE_LEN == 2000


def test_max_suggestion_len_equals_2000() -> None:
    # Mirrors MAX_MESSAGE_LEN: a Redo suggestion is at most one short directive.
    assert limits.MAX_SUGGESTION_LEN == 2000


def test_max_instructions_len_equals_8192() -> None:
    # 8 192 chars = ~3 pages of text; sufficient for detailed red-team briefs.
    assert limits.MAX_INSTRUCTIONS_LEN == 8192


def test_max_key_len_equals_400() -> None:
    # Compound key format: {committee}/{element_id}/{specialist_id} — 400 is generous
    # for three segments while preventing abuse of the in-memory disabled set.
    assert limits.MAX_KEY_LEN == 400


def test_max_id_len_equals_200() -> None:
    # Ensemble-defined IDs are short slugs; 200 chars bounds the field safely.
    assert limits.MAX_ID_LEN == 200


def test_message_len_not_larger_than_instructions_len() -> None:
    # A single chat message should never exceed the initial instructions ceiling.
    assert limits.MAX_MESSAGE_LEN <= limits.MAX_INSTRUCTIONS_LEN


def test_suggestion_len_not_larger_than_message_len() -> None:
    # A Redo note is no richer than a regular chat message.
    assert limits.MAX_SUGGESTION_LEN <= limits.MAX_MESSAGE_LEN


def _max_length(field_info) -> int | None:
    """Extract max_length from a Pydantic v2 FieldInfo metadata list."""
    for meta in field_info.metadata:
        if hasattr(meta, "max_length"):
            return meta.max_length
    return None


def test_route_models_use_shared_limits() -> None:
    """Smoke-test that route models pick up the shared limits (not stale local copies)."""
    from athena.server.routes.chat import ChatRequest
    from athena.server.routes.report_chat import ReportChatRequest
    from athena.server.routes.gate_decision import GateDecisionRequest
    from athena.server.routes.loop_gate import LoopGateDecisionRequest
    from athena.server.routes.engagements import StartEngagementRequest
    from athena.server.routes.specialist_config import SpecialistConfigRequest

    assert _max_length(ChatRequest.model_fields["message"]) == limits.MAX_MESSAGE_LEN
    assert _max_length(ReportChatRequest.model_fields["message"]) == limits.MAX_MESSAGE_LEN
    assert _max_length(GateDecisionRequest.model_fields["suggestion"]) == limits.MAX_SUGGESTION_LEN
    assert _max_length(LoopGateDecisionRequest.model_fields["suggestion"]) == limits.MAX_SUGGESTION_LEN
    assert _max_length(StartEngagementRequest.model_fields["instructions"]) == limits.MAX_INSTRUCTIONS_LEN
    assert _max_length(SpecialistConfigRequest.model_fields["key"]) == limits.MAX_KEY_LEN
