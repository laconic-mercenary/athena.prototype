"""Model backend abstraction.

All LLM calls go through ModelBackend. No other module may call a provider
SDK directly. Each backend reads its own API key from the environment at
construction and never passes it to callers or writes it to logs.

Each ModelBackend instance manages a single conversation. Create a new
instance per agent run — call begin() to initialize, then alternate
complete() and record_tool_results() until end_turn.

This module defines the provider-neutral surface: the ModelBackend interface,
the normalized types (ToolDefinition, ToolCall, ModelResponse), and the
make_backend() factory. The concrete implementations live in athena.model_backends
(anthropic.py, ollama.py, fake.py).

Adding a new provider means writing a new ModelBackend subclass in
athena.model_backends and registering it in make_backend(). The agent loop and
committee code are unaffected. For convenience the concrete backends are also
importable from this module (e.g. `from athena.model_backend import FakeBackend`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from athena.model_backends.anthropic import AnthropicBackend
    from athena.model_backends.fake import FakeBackend
    from athena.model_backends.ollama import OllamaBackend


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
# INTERFACE #
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


###############
# FACTORY #
###############

BackendFactory = Callable[..., ModelBackend]


def make_backend(provider: str, config: dict | None = None) -> ModelBackend:
    """Instantiate the correct backend for the given provider name.

    config carries provider-specific options and is fully optional (None -> no options).
    Keys the factory reads:
      - ollama_base_url: str — REQUIRED for provider "ollama". The endpoint URL. There is
        no global default; every ollama element names its own endpoint in the manifest.
      - extra_headers: dict[str, str] — transport auth headers (e.g. Modal proxy auth or a
        Bearer Authorization), already resolved from the environment by the caller via the
        element's auth_headers_env map. Each ollama endpoint owns its own auth this way.
    Unknown keys are ignored, so new providers can add their own without touching callers.

    Concrete backends are imported lazily here so this module has no import-time
    dependency on its own implementations (keeps the package import graph acyclic).
    """
    config = config or {}
    if provider == "anthropic":
        from athena.model_backends.anthropic import AnthropicBackend
        return AnthropicBackend()
    if provider == "ollama":
        from athena.model_backends.ollama import OllamaBackend
        url = config.get("ollama_base_url")
        if not url:
            raise ValueError(
                "ollama_base_url is required in config when provider is 'ollama' — "
                "declare it on the ensemble element (there is no global default)"
            )
        return OllamaBackend(
            base_url=url,
            extra_headers=config.get("extra_headers"),
        )
    raise ValueError(f"Unknown provider: {provider!r}")


# Backward-compatible re-exports. The concrete backends live in athena.model_backends
# but many callers/tests do `from athena.model_backend import FakeBackend` etc. These
# resolve lazily (PEP 562) so importing this module never eagerly pulls in a provider
# SDK, and there is no import cycle with the model_backends package.
_LAZY_BACKENDS = {
    "AnthropicBackend": "athena.model_backends.anthropic",
    "OllamaBackend": "athena.model_backends.ollama",
    "FakeBackend": "athena.model_backends.fake",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_BACKENDS.get(name)
    if module_path is not None:
        import importlib
        return getattr(importlib.import_module(module_path), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ToolDefinition",
    "ToolCall",
    "ModelResponse",
    "ModelBackend",
    "BackendFactory",
    "make_backend",
    "AnthropicBackend",
    "OllamaBackend",
    "FakeBackend",
]
