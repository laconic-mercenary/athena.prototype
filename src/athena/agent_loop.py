"""Core agent loop.

Runs a single agent: calls the model, executes tool calls, and loops until
the model emits a final text response or the iteration cap is reached.

The loop has no knowledge of any provider's message format. All conversation
history is managed inside the ModelBackend instance.

Verbose agent reasoning is logged at DEBUG level under the agent's own logger
(e.g. "recon:network_scout"). Enable it by setting the athena logger to DEBUG
via configure_logging(verbose=True).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from athena.model_backend import ModelBackend, ToolDefinition


ToolDispatch = Callable[[str, dict[str, Any]], str]


class MaxIterationsExceeded(RuntimeError):
    pass


def run_agent(
    *,
    agent_id: str,
    system: str,
    initial_message: str,
    tools: list[ToolDefinition],
    tool_dispatch: ToolDispatch,
    backend: ModelBackend,
    model: str,
    max_iterations: int,
    max_tokens: int = 4096,
) -> str:
    """Run an agent loop and return the final text response.

    Each call to the model counts as one iteration. Raises MaxIterationsExceeded
    if the cap is hit before the model emits end_turn.
    """
    logger = logging.getLogger(agent_id)

    # Initialize the backend's conversation state for this agent run.
    # Each ModelBackend instance is single-use per conversation.
    backend.begin(system=system, initial_message=initial_message)

    for _ in range(max_iterations):
        # Send the current conversation state to the model and get its next action.
        response = backend.complete(model=model, tools=tools or None, max_tokens=max_tokens)

        if response.stop_reason == "end_turn":
            # The model is done — it produced a final text response (the artifact).
            logger.debug("end_turn: %r", (response.text or "")[:120])
            return response.text or ""

        if response.stop_reason == "max_tokens":
            # Output budget exhausted mid-response — the result is unusable.
            raise RuntimeError(f"{agent_id}: model hit max_tokens before completing")

        # stop_reason == "tool_use": execute each requested tool, collect results.
        # tool_dispatch is caller-supplied: (name, input) -> result string.
        results: list[str] = []
        for tc in response.tool_calls:
            logger.debug("tool_call: %s(%s)", tc.name, json.dumps(tc.input))
            result = tool_dispatch(tc.name, tc.input)
            logger.debug("tool_result: %s", result[:200])
            results.append(result)

        # Hand the assistant turn and results back to the backend.
        # The backend appends them to its conversation history in whatever
        # format its provider requires — the loop never sees those details.
        backend.record_tool_results(response, results)

    raise MaxIterationsExceeded(
        f"{agent_id}: reached max_iterations={max_iterations} without end_turn"
    )
