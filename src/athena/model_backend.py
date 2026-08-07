"""Model backend abstraction.

All LLM calls go through ModelBackend. No other module may call a provider
SDK directly. The API key is read from the environment here and never passed
to callers or written to logs.

Each ModelBackend instance manages a single conversation. Create a new
instance per agent run — call begin() to initialize, then alternate
complete() and record_tool_results() until end_turn.

Adding a new provider means writing a new ModelBackend subclass and
registering it in make_backend(). The agent loop and committee code are
unaffected.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

from athena import env_vars


###############
# CONSTS / GLOBALS #
###############

_OLLAMA_FINISH_REASON: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


###############
# CUSTOM TYPES #
###############

@dataclass(frozen=True)
class ToolDefinition:
    """Provider-neutral tool specification. Each backend translates to its own format."""

    name: str
    description: str
    parameters: dict  # JSON Schema object describing the tool's input


@dataclass
class ToolCall:
    """A single tool-use request returned by the model in a complete() response.

    Normalized across providers: the id is provider-assigned and must be echoed back
    in record_tool_results() so the backend can build a valid conversation history.
    """

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelResponse:
    """Normalized response from any model backend after a single complete() call.

    The agent loop inspects stop_reason to decide its next action: execute tool calls
    and loop (tool_use), surface the final answer (end_turn), or raise a hard error
    (max_tokens — the loop has no room to recover from a truncated response).
    """

    stop_reason: str           # "end_turn" | "tool_use" | "max_tokens"
    text: str | None           # present when stop_reason == "end_turn"
    tool_calls: list[ToolCall] = field(default_factory=list)


###############
# CLASSES #
###############

class ModelBackend(ABC):
    """Stateful conversation manager. One instance per agent run."""

    @abstractmethod
    def begin(self, *, system: str, initial_message: str) -> None:
        """Initialize the conversation with a system prompt and first user message."""
        ...

    @abstractmethod
    def complete(
        self,
        *,
        model: str,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int,
        temperature: float | None = None,
    ) -> ModelResponse:
        """Call the model with the current conversation state and return its response."""
        ...

    @abstractmethod
    def record_tool_results(
        self,
        assistant_response: ModelResponse,
        results: list[str],
    ) -> None:
        """Append the assistant's tool-use turn and results to the conversation history.

        results[i] corresponds to assistant_response.tool_calls[i].
        Each backend writes these in its own native format.
        """
        ...

    @abstractmethod
    def record_assistant_message(self, text: str) -> None:
        """Append a plain assistant text turn to history.

        complete() does NOT record the assistant turn (record_tool_results does that
        for tool_use). When the loop re-prompts after an end_turn, it must first record
        the assistant's text here so history stays a valid alternating sequence and the
        model keeps sight of what it just said.
        """
        ...

    @abstractmethod
    def inject_user_message(self, text: str) -> None:
        """Append an operator message mid-run for committee leader chat.

        Called between agent loop iterations to inject operator input so the
        model sees it on its next complete() call.
        """
        ...

    @abstractmethod
    def append_harness_message(self, text: str) -> None:
        """Append a harness-generated user turn (not an operator message).

        Used for gate callbacks injected into the orchestrator conversation.
        Handles provider alternation constraints the same way inject_user_message
        does, but without the [Operator]: prefix.
        """
        ...


class AnthropicBackend(ModelBackend):
    """ModelBackend backed by the Anthropic Messages API.

    Manages conversation history in Anthropic's native alternating role/content format.
    The API key is read from ATHENA_ANTHROPIC_API_KEY at construction and never stored elsewhere.
    Tool definitions are translated to Anthropic's input_schema format on each complete() call.
    """

    def __init__(self) -> None:
        api_key = os.environ.get(env_vars.ANTHROPIC_API_KEY)
        if not api_key:
            raise RuntimeError(f"{env_vars.ANTHROPIC_API_KEY} environment variable is not set")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._system: str = ""
        self._messages: list[dict] = []

    def begin(self, *, system: str, initial_message: str) -> None:
        self._system = system
        self._messages = [{"role": "user", "content": initial_message}]

    def complete(
        self,
        *,
        model: str,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int,
        temperature: float | None = None,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "system": self._system,
            "messages": self._messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if tools:
            # Anthropic uses "input_schema" where OpenAI-compatible APIs use "parameters".
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        resp = self._client.messages.create(**kwargs)

        text: str | None = None
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        return ModelResponse(stop_reason=resp.stop_reason, text=text, tool_calls=tool_calls)

    def record_tool_results(
        self,
        assistant_response: ModelResponse,
        results: list[str],
    ) -> None:
        # Anthropic requires the assistant's tool_use blocks to appear in the
        # assistant turn before the matching tool_result blocks arrive.
        assistant_content: list[dict] = []
        if assistant_response.text:
            assistant_content.append({"type": "text", "text": assistant_response.text})
        for tc in assistant_response.tool_calls:
            assistant_content.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            )
        self._messages.append({"role": "assistant", "content": assistant_content})

        # All results go in one user turn — Anthropic enforces role alternation.
        self._messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tc.id, "content": result}
                for tc, result in zip(assistant_response.tool_calls, results)
            ],
        })

    def record_assistant_message(self, text: str) -> None:
        if text:
            self._messages.append({"role": "assistant", "content": text})

    def inject_user_message(self, text: str) -> None:
        formatted = f"[Operator]: {text}"
        # After record_tool_results the last message is already a user turn
        # (containing tool_result blocks). Anthropic forbids consecutive user
        # roles, so we merge the operator text into that existing turn as an
        # additional text block rather than appending a new user message.
        if self._messages and self._messages[-1]["role"] == "user":
            content = self._messages[-1]["content"]
            if isinstance(content, list):
                content.append({"type": "text", "text": formatted})
            else:
                self._messages[-1]["content"] = [
                    {"type": "text", "text": str(content)},
                    {"type": "text", "text": formatted},
                ]
        else:
            self._messages.append({"role": "user", "content": formatted})

    def append_harness_message(self, text: str) -> None:
        # Same merge logic as inject_user_message but without the operator prefix.
        if self._messages and self._messages[-1]["role"] == "user":
            content = self._messages[-1]["content"]
            if isinstance(content, list):
                content.append({"type": "text", "text": text})
            else:
                self._messages[-1]["content"] = [
                    {"type": "text", "text": str(content)},
                    {"type": "text", "text": text},
                ]
        else:
            self._messages.append({"role": "user", "content": text})


class OllamaBackend(ModelBackend):
    """Calls any OpenAI-compatible /v1/chat/completions endpoint (Ollama or vLLM).

    If the ATHENA_OLLAMA_API_KEY environment variable is set, its value is sent as a
    Bearer token — required when pointing at a Modal-hosted vLLM endpoint.
    """

    def __init__(
        self,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
        use_global_api_key: bool = True,
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._messages: list[dict] = []
        # The global ATHENA_OLLAMA_API_KEY Bearer belongs to the global ATHENA_OLLAMA_BASE_URL endpoint. A
        # specialist that overrides its own base_url owns its auth via extra_headers instead, so
        # we do NOT apply the global key to it — that keeps distinct endpoints' creds from mixing.
        self._api_key: str | None = (os.environ.get(env_vars.OLLAMA_API_KEY) or None) if use_global_api_key else None
        # Extra transport headers (e.g. Modal proxy auth: Modal-Key / Modal-Secret), already
        # resolved from the environment by the caller.
        self._extra_headers: dict[str, str] = extra_headers or {}

    def begin(self, *, system: str, initial_message: str) -> None:
        # Ollama/OpenAI uses a system message in the messages list,
        # not a separate top-level parameter like Anthropic.
        self._messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": initial_message},
        ]

    def complete(
        self,
        *,
        model: str,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int,
        temperature: float | None = None,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            # OpenAI tool format wraps each definition in a {"type": "function", ...} envelope.
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self._extra_headers)
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama API error {e.code}: {detail}") from e

        choice = data["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        text = message.get("content") or None
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            # OpenAI encodes tool input as a JSON string; some models return a dict directly.
            raw_args = tc["function"]["arguments"]
            input_dict = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            tool_calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], input=input_dict))

        stop_reason = _OLLAMA_FINISH_REASON.get(finish_reason, "end_turn")
        return ModelResponse(stop_reason=stop_reason, text=text, tool_calls=tool_calls)

    def record_tool_results(
        self,
        assistant_response: ModelResponse,
        results: list[str],
    ) -> None:
        # Append the assistant's turn with its tool_calls.
        self._messages.append({
            "role": "assistant",
            "content": assistant_response.text,  # may be None
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        # OpenAI expects arguments as a JSON string.
                        "arguments": json.dumps(tc.input),
                    },
                }
                for tc in assistant_response.tool_calls
            ],
        })
        # Each tool result is its own message in OpenAI format — unlike Anthropic,
        # which batches them all into one user turn.
        for tc, result in zip(assistant_response.tool_calls, results):
            self._messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    def record_assistant_message(self, text: str) -> None:
        if text:
            self._messages.append({"role": "assistant", "content": text})

    def inject_user_message(self, text: str) -> None:
        # OpenAI-compatible format allows a user message after tool messages
        # without the alternation constraint Anthropic imposes.
        self._messages.append({"role": "user", "content": f"[Operator]: {text}"})

    def append_harness_message(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})


class FakeBackend(ModelBackend):
    """Scriptable fake for tests. Responses are consumed in order."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._queue = list(responses)
        self.system: str = ""
        self.initial_message: str = ""
        self.calls: list[dict[str, Any]] = []
        self.recorded: list[tuple[ModelResponse, list[str]]] = []
        self.injected: list[str] = []

    def begin(self, *, system: str, initial_message: str) -> None:
        self.system = system
        self.initial_message = initial_message

    def complete(
        self,
        *,
        model: str,
        tools: list[ToolDefinition] | None = None,
        max_tokens: int,
        temperature: float | None = None,
    ) -> ModelResponse:
        self.calls.append({"model": model, "tools": tools, "max_tokens": max_tokens, "temperature": temperature})
        if not self._queue:
            raise RuntimeError("FakeBackend has no more responses queued")
        return self._queue.pop(0)

    def record_tool_results(
        self,
        assistant_response: ModelResponse,
        results: list[str],
    ) -> None:
        self.recorded.append((assistant_response, results))

    def record_assistant_message(self, text: str) -> None:
        self.recorded.append(("assistant_text", text))

    def inject_user_message(self, text: str) -> None:
        self.injected.append(text)

    def append_harness_message(self, text: str) -> None:
        self.injected.append(text)


###############
# FUNCTIONS #
###############

BackendFactory = Callable[..., ModelBackend]


def make_backend(
    provider: str,
    ollama_base_url: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> ModelBackend:
    """Instantiate the correct backend for the given provider name.

    When ollama_base_url is passed explicitly (a per-element endpoint override), that endpoint
    owns its auth via extra_headers — the global ATHENA_OLLAMA_API_KEY Bearer is not applied to it.
    """
    if provider == "anthropic":
        return AnthropicBackend()
    if provider == "ollama":
        overridden = ollama_base_url is not None
        url = ollama_base_url or os.environ.get(env_vars.OLLAMA_BASE_URL)
        if not url:
            raise ValueError(
                "ollama_base_url is required when provider is 'ollama' "
                f"(pass it explicitly or set {env_vars.OLLAMA_BASE_URL})"
            )
        return OllamaBackend(
            base_url=url,
            extra_headers=extra_headers,
            use_global_api_key=not overridden,
        )
    raise ValueError(f"Unknown provider: {provider!r}")
