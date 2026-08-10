"""Anthropic Messages API backend.

Concrete ModelBackend backed by the Anthropic Messages API. Shared types and the
ModelBackend interface live in athena.model_backend; this module only implements
the Anthropic-specific wire format.
"""

from __future__ import annotations

from typing import Any

import anthropic

from athena import env_vars
from athena.model_backend import ModelBackend, ModelResponse, ToolCall, ToolDefinition

# Anthropic-specific environment variable names. Kept here rather than in the shared
# env_vars module because they are meaningful only to this backend — a provider's
# credentials never leak into the harness-wide namespace.
API_KEY_ENV = "ATHENA_ANTHROPIC_API_KEY"


class AnthropicBackend(ModelBackend):
    """ModelBackend backed by the Anthropic Messages API.

    Manages conversation history in Anthropic's native alternating role/content format.
    The API key is read from ATHENA_ANTHROPIC_API_KEY (API_KEY_ENV) at construction and
    never stored elsewhere.
    Tool definitions are translated to Anthropic's input_schema format on each complete() call.
    """

    def __init__(self) -> None:
        api_key = env_vars.get_required(API_KEY_ENV)
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
