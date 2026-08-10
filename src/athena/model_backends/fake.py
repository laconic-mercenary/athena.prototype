"""Scriptable fake backend for tests.

Concrete ModelBackend that replays a queue of pre-built responses. Shared types and
the ModelBackend interface live in athena.model_backend.
"""

from __future__ import annotations

from typing import Any

from athena.model_backend import ModelBackend, ModelResponse, ToolDefinition


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
