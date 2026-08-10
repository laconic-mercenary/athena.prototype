"""OpenAI-compatible (Ollama / vLLM) backend.

Concrete ModelBackend that calls any OpenAI-compatible /v1/chat/completions endpoint.
Used for locally-served models (Ollama), self-hosted vLLM, and Modal-hosted vLLM
endpoints (Foundation-Sec, Kimi-K3, ...). Shared types and the ModelBackend interface
live in athena.model_backend.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from athena.model_backend import ModelBackend, ModelResponse, ToolCall, ToolDefinition

# OpenAI/Ollama finish_reason -> normalized ModelResponse.stop_reason.
_OLLAMA_FINISH_REASON: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


class OllamaBackend(ModelBackend):
    """Calls any OpenAI-compatible /v1/chat/completions endpoint (Ollama or vLLM).

    The endpoint URL and all auth are supplied by the caller — there is no global default.
    Each ollama element in the manifest names its own endpoint (ollama_base_url) and its own
    auth headers (auth_headers_env), so distinct endpoints never share credentials.
    """

    def __init__(
        self,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._messages: list[dict] = []
        # Per-endpoint auth transport headers, already resolved from the environment by the
        # caller via the element's auth_headers_env map. This is the ONLY auth mechanism —
        # e.g. Modal proxy (Modal-Key / Modal-Secret) or a Bearer (Authorization: Bearer <tok>).
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
