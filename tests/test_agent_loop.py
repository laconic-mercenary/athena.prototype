"""Tests for the agent loop."""

import pytest

from athena.agent_loop import MAX_END_TURN_CORRECTIONS, MaxIterationsExceeded, run_agent
from athena.model_backend import FakeBackend, ModelResponse, ToolCall, ToolDefinition

_TEST_MAX_TOKENS = 4_096


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool(name: str, input: dict, tc_id: str = "tc1") -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=input)],
    )


def _run(backend: FakeBackend, tool_dispatch=None, max_iterations: int = 5, agent_id: str = "test:agent") -> str:
    return run_agent(
        agent_id=agent_id,
        system="you are a test agent",
        initial_message="go",
        tools=[],
        tool_dispatch=tool_dispatch or (lambda n, i: "ok"),
        backend=backend,
        model="claude-haiku-4-5",
        max_iterations=max_iterations,
        max_tokens=_TEST_MAX_TOKENS,
    )


def test_immediate_end_turn_returns_text() -> None:
    backend = FakeBackend([_end('{"done": true}')])
    assert _run(backend) == '{"done": true}'
    assert len(backend.calls) == 1


def test_begin_is_called_with_system_and_message() -> None:
    backend = FakeBackend([_end("ok")])
    run_agent(
        agent_id="test:agent",
        system="the system prompt",
        initial_message="the first message",
        tools=[],
        tool_dispatch=lambda n, i: "ok",
        backend=backend,
        model="m",
        max_iterations=5,
        max_tokens=_TEST_MAX_TOKENS,
    )
    assert backend.system == "the system prompt"
    assert backend.initial_message == "the first message"


def test_tool_call_dispatched_and_result_recorded() -> None:
    dispatched: list[tuple] = []

    def dispatch(name: str, input: dict) -> str:
        dispatched.append((name, input))
        return f"result of {name}"

    backend = FakeBackend([
        _tool("check_port", {"host": "target", "port": 80}),
        _end("port is open"),
    ])
    result = _run(backend, tool_dispatch=dispatch)

    assert result == "port is open"
    assert dispatched == [("check_port", {"host": "target", "port": 80})]
    assert len(backend.calls) == 2
    assert len(backend.recorded) == 1
    assert backend.recorded[0][1] == ["result of check_port"]


def test_multiple_tool_calls_in_sequence() -> None:
    dispatched: list[str] = []

    def dispatch(name: str, input: dict) -> str:
        dispatched.append(name)
        return "ok"

    backend = FakeBackend([
        _tool("nmap_scan", {"host": "target"}, tc_id="tc1"),
        _tool("http_get", {"url": "http://target/"}, tc_id="tc2"),
        _end("done"),
    ])
    _run(backend, tool_dispatch=dispatch)

    assert dispatched == ["nmap_scan", "http_get"]
    assert len(backend.calls) == 3
    assert len(backend.recorded) == 2


def test_max_iterations_exceeded() -> None:
    backend = FakeBackend([
        _tool("check_port", {"host": "target", "port": 80}, tc_id=f"tc{i}")
        for i in range(10)
    ])
    with pytest.raises(MaxIterationsExceeded, match="max_iterations=3"):
        _run(backend, max_iterations=3)


def test_max_tokens_raises_runtime_error() -> None:
    backend = FakeBackend([ModelResponse(stop_reason="max_tokens", text=None)])
    with pytest.raises(RuntimeError, match="max_tokens"):
        _run(backend)


def test_debug_output_via_logging(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    backend = FakeBackend([
        _tool("check_port", {"host": "target", "port": 22}),
        _end("done"),
    ])
    with caplog.at_level(logging.DEBUG, logger="test:scout"):
        _run(backend, tool_dispatch=lambda n, i: "Port target:22 is open", agent_id="test:scout")
    assert "tool_call:" in caplog.text
    assert "tool_result:" in caplog.text
    assert "end_turn:" in caplog.text


def test_temperature_passed_through_to_backend() -> None:
    backend = FakeBackend([_end("done")])
    run_agent(
        agent_id="test:agent",
        system="sys",
        initial_message="go",
        tools=[],
        tool_dispatch=lambda n, i: "ok",
        backend=backend,
        model="m",
        max_iterations=5,
        max_tokens=_TEST_MAX_TOKENS,
        temperature=0.4,
    )
    assert backend.calls[0]["temperature"] == 0.4


def test_temperature_defaults_to_none() -> None:
    backend = FakeBackend([_end("done")])
    _run(backend)
    assert backend.calls[0]["temperature"] is None


def test_on_end_turn_accept_returns_immediately() -> None:
    backend = FakeBackend([_end('{"ok": true}')])
    result = run_agent(
        agent_id="t", system="s", initial_message="go", tools=[],
        tool_dispatch=lambda n, i: "ok", backend=backend, model="m",
        max_iterations=5, max_tokens=_TEST_MAX_TOKENS,
        on_end_turn=lambda text: None,  # accept
    )
    assert result == '{"ok": true}'
    assert len(backend.calls) == 1


def test_on_end_turn_reprompts_then_accepts() -> None:
    # First end_turn is conversational (rejected); second is the real artifact.
    backend = FakeBackend([_end("waiting for approval"), _end('{"ok": true}')])
    seen: list[str] = []

    def validate(text: str) -> str | None:
        seen.append(text)
        return "use a tool" if text == "waiting for approval" else None

    result = run_agent(
        agent_id="t", system="s", initial_message="go", tools=[],
        tool_dispatch=lambda n, i: "ok", backend=backend, model="m",
        max_iterations=5, max_tokens=_TEST_MAX_TOKENS, on_end_turn=validate,
    )
    assert result == '{"ok": true}'
    assert seen == ["waiting for approval", '{"ok": true}']
    assert len(backend.calls) == 2
    # The rejected assistant turn was recorded, and the correction appended (as harness).
    assert ("assistant_text", "waiting for approval") in backend.recorded
    assert "use a tool" in backend.injected


def test_on_end_turn_correction_budget_is_bounded() -> None:
    # A model that never complies: after MAX corrections the text is returned as-is
    # (the caller then surfaces a clear error) rather than looping forever.
    n = MAX_END_TURN_CORRECTIONS + 1
    backend = FakeBackend([_end("nope") for _ in range(n)])
    result = run_agent(
        agent_id="t", system="s", initial_message="go", tools=[],
        tool_dispatch=lambda n, i: "ok", backend=backend, model="m",
        max_iterations=n + 2, max_tokens=_TEST_MAX_TOKENS,
        on_end_turn=lambda text: "still wrong",
    )
    assert result == "nope"
    assert len(backend.calls) == n  # MAX corrections, then accepted on the next


def test_on_end_turn_budget_resets_after_tool_use() -> None:
    # A tool call between rejections resets the consecutive-correction budget.
    backend = FakeBackend([
        _end("chat"),                    # rejected (correction 1)
        _tool("ask_operator", {}),       # progress → resets budget
        _end("chat"),                    # rejected again (correction 1, not 2)
        _end('{"ok": true}'),            # accepted
    ])
    result = run_agent(
        agent_id="t", system="s", initial_message="go", tools=[],
        tool_dispatch=lambda n, i: "ok", backend=backend, model="m",
        max_iterations=8, max_tokens=_TEST_MAX_TOKENS,
        on_end_turn=lambda text: "use a tool" if text == "chat" else None,
    )
    assert result == '{"ok": true}'
    assert len(backend.calls) == 4


def test_tools_passed_through_to_backend() -> None:
    td = ToolDefinition(
        name="nmap_scan",
        description="Scan ports",
        parameters={"type": "object", "properties": {"host": {"type": "string"}}},
    )
    backend = FakeBackend([_end("done")])
    run_agent(
        agent_id="test:agent",
        system="sys",
        initial_message="go",
        tools=[td],
        tool_dispatch=lambda n, i: "ok",
        backend=backend,
        model="m",
        max_iterations=5,
        max_tokens=_TEST_MAX_TOKENS,
    )
    assert backend.calls[0]["tools"] == [td]
