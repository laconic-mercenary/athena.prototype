"""Tests for the model backend abstraction."""

import pytest

from athena.model_backend import FakeBackend, ModelResponse, ToolCall, ToolDefinition


def _end(text: str) -> ModelResponse:
    return ModelResponse(stop_reason="end_turn", text=text)


def _tool(name: str, input: dict, tc_id: str = "tc1") -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tc_id, name=name, input=input)],
    )


def test_fake_backend_returns_responses_in_order() -> None:
    backend = FakeBackend([_end("first"), _end("second")])
    backend.begin(system="s", initial_message="go")
    r1 = backend.complete(model="m")
    r2 = backend.complete(model="m")
    assert r1.text == "first"
    assert r2.text == "second"


def test_fake_backend_records_begin() -> None:
    backend = FakeBackend([_end("ok")])
    backend.begin(system="sys", initial_message="hello")
    assert backend.system == "sys"
    assert backend.initial_message == "hello"


def test_fake_backend_records_calls() -> None:
    backend = FakeBackend([_end("ok")])
    backend.begin(system="s", initial_message="go")
    backend.complete(model="claude-haiku-4-5")
    assert len(backend.calls) == 1
    assert backend.calls[0]["model"] == "claude-haiku-4-5"


def test_fake_backend_raises_when_exhausted() -> None:
    backend = FakeBackend([_end("only one")])
    backend.begin(system="s", initial_message="go")
    backend.complete(model="m")
    with pytest.raises(RuntimeError, match="no more responses"):
        backend.complete(model="m")


def test_fake_backend_records_tool_results() -> None:
    resp = _tool("nmap_scan", {"host": "target"})
    backend = FakeBackend([resp, _end("done")])
    backend.begin(system="s", initial_message="go")
    r = backend.complete(model="m")
    backend.record_tool_results(r, ["2 ports open"])
    assert len(backend.recorded) == 1
    assert backend.recorded[0][1] == ["2 ports open"]


def test_fake_backend_tool_response_shape() -> None:
    backend = FakeBackend([_tool("nmap_scan", {"host": "target"})])
    backend.begin(system="s", initial_message="go")
    resp = backend.complete(model="m", tools=[])
    assert resp.stop_reason == "tool_use"
    assert resp.text is None
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "nmap_scan"
    assert resp.tool_calls[0].input == {"host": "target"}


def test_tool_definition_is_frozen() -> None:
    td = ToolDefinition(
        name="check_port",
        description="Check if a port is open",
        parameters={"type": "object", "properties": {"host": {"type": "string"}}},
    )
    with pytest.raises(Exception):
        td.name = "other"  # type: ignore[misc]


def test_anthropic_backend_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from athena.model_backend import AnthropicBackend
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicBackend()


# ---------------------------------------------------------------------------
# OllamaBackend message format tests (no live server required)
# ---------------------------------------------------------------------------


def test_ollama_begin_creates_system_and_user_messages() -> None:
    from athena.model_backend import OllamaBackend
    backend = OllamaBackend(base_url="http://localhost:11434")
    backend.begin(system="You are a scout", initial_message="start recon")
    assert backend._messages[0] == {"role": "system", "content": "You are a scout"}
    assert backend._messages[1] == {"role": "user", "content": "start recon"}


def test_ollama_record_tool_results_appends_correct_format() -> None:
    from athena.model_backend import OllamaBackend
    backend = OllamaBackend(base_url="http://localhost:11434")
    backend.begin(system="sys", initial_message="go")

    resp = ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id="tc1", name="nmap_scan", input={"host": "target"})],
    )
    backend.record_tool_results(resp, ["2 ports open: 22, 80"])

    # system + user + assistant (tool_calls) + tool result = 4 messages
    assert len(backend._messages) == 4

    assistant_msg = backend._messages[2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "nmap_scan"
    assert assistant_msg["tool_calls"][0]["function"]["arguments"] == '{"host": "target"}'

    tool_msg = backend._messages[3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "tc1"
    assert tool_msg["content"] == "2 ports open: 22, 80"


def test_ollama_record_multiple_tool_results() -> None:
    from athena.model_backend import OllamaBackend
    backend = OllamaBackend(base_url="http://localhost:11434")
    backend.begin(system="sys", initial_message="go")

    resp = ModelResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[
            ToolCall(id="tc1", name="check_port", input={"host": "target", "port": 22}),
            ToolCall(id="tc2", name="check_port", input={"host": "target", "port": 80}),
        ],
    )
    backend.record_tool_results(resp, ["open", "open"])

    # system + user + assistant + tool(tc1) + tool(tc2) = 5 messages
    assert len(backend._messages) == 5
    assert backend._messages[3]["tool_call_id"] == "tc1"
    assert backend._messages[4]["tool_call_id"] == "tc2"


# ---------------------------------------------------------------------------
# make_backend factory
# ---------------------------------------------------------------------------


def test_make_backend_ollama_returns_ollama_instance() -> None:
    from athena.model_backend import OllamaBackend, make_backend
    backend = make_backend("ollama", ollama_base_url="http://localhost:11434")
    assert isinstance(backend, OllamaBackend)


def test_make_backend_ollama_requires_base_url() -> None:
    from athena.model_backend import make_backend
    with pytest.raises(ValueError, match="ollama_base_url"):
        make_backend("ollama")


def test_make_backend_unknown_provider_raises() -> None:
    from athena.model_backend import make_backend
    with pytest.raises(ValueError, match="Unknown provider"):
        make_backend("openai")
