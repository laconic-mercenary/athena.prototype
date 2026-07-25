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
import queue
from typing import Any, Callable

from athena.model_backend import ModelBackend, ToolDefinition


ToolDispatch = Callable[[str, dict[str, Any]], str]


# Output-token ceiling for committee leaders and specialists that emit a full
# artifact (plan, report, section) in one final turn. If a single call hits its
# max_tokens ceiling the loop raises a hard RuntimeError and the pipeline halts,
# so this is sized with wide headroom over any realistic artifact. It is a ceiling
# only — billing is on tokens actually generated — so being generous is free.
SYNTHESIS_MAX_TOKENS = 16384


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
    max_tokens: int,
    temperature: float | None = None,
    operator_queue: queue.Queue | None = None,
    on_operator_reply: Callable[[str], None] | None = None,
) -> str:
    """Run an agent loop and return the final text response.

    Each call to the model counts as one iteration. Raises MaxIterationsExceeded
    if the cap is hit before the model emits end_turn.
    """
    logger = logging.getLogger(agent_id)

    # Initialize the backend's conversation state for this agent run.
    # Each ModelBackend instance is single-use per conversation.
    backend.begin(system=system, initial_message=initial_message)

    # True when operator messages were injected at the end of the previous
    # iteration; we capture the model's next text response as the reply.
    _pending_operator_reply = False

    for _ in range(max_iterations):
        # Send the current conversation state to the model and get its next action.
        response = backend.complete(model=model, tools=tools or None, max_tokens=max_tokens, temperature=temperature)

        # Surface the model's conversational reply to an operator injection.
        # Only capture text from tool_use responses — end_turn text is the artifact JSON.
        if _pending_operator_reply and on_operator_reply and response.stop_reason == "tool_use":
            text = (response.text or "").strip()
            if text:
                on_operator_reply(text)
        _pending_operator_reply = False

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

        # Drain any operator messages queued between iterations and inject
        # them as user turns so the model sees them on the next complete().
        # The [OPERATOR INTERRUPT] tag matches the framing in leader system prompts
        # so the model recognises it as a mid-task note, not a new conversation.
        if operator_queue is not None:
            _had_inject = False
            while True:
                try:
                    msg = operator_queue.get_nowait()
                    backend.inject_user_message(f"[OPERATOR INTERRUPT]: {msg}")
                    logger.debug("operator message injected: %s", msg[:120])
                    _had_inject = True
                except queue.Empty:
                    break
            if _had_inject:
                _pending_operator_reply = True

    raise MaxIterationsExceeded(
        f"{agent_id}: reached max_iterations={max_iterations} without end_turn"
    )
