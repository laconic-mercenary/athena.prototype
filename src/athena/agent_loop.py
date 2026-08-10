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


###############
# CONSTS / GLOBALS #
###############

# Output-token ceiling for committee leaders and specialists that emit a full
# artifact (plan, report, section) in one final turn. If a single call hits its
# max_tokens ceiling the loop raises a hard RuntimeError and the pipeline halts,
# so this is sized with wide headroom over any realistic artifact. It is a ceiling
# only — billing is on tokens actually generated — so being generous is free.
SYNTHESIS_MAX_TOKENS = 16384

# How many times we re-prompt a model that ends its turn without producing the
# expected result (e.g. a leader that ends conversationally after reply_operator
# instead of calling finish()). Bounds the correction loop; beyond it we give up
# and return the text as-is so the caller can surface a clear error.
MAX_END_TURN_CORRECTIONS = 4


###############
# CUSTOM TYPES #
###############

ToolDispatch = Callable[[str, dict[str, Any]], str]


###############
# CLASSES #
###############

class MaxIterationsExceeded(RuntimeError):
    """Raised by run_agent() when the model has not produced a final response within max_iterations.

    The caller (committee_runner or orchestrator) treats this as a hard failure —
    the agent is considered stuck and the run is marked failed.
    """


###############
# FUNCTIONS #
###############

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
    on_model_response: Callable[[str, str], None] | None = None,
    operator_queue: queue.Queue | None = None,
    on_operator_reply: Callable[[str], None] | None = None,
    on_end_turn: Callable[[str], "str | None"] | None = None,
) -> str:
    """Run an agent loop and return the final text response.

    Each call to the model counts as one iteration. Raises MaxIterationsExceeded
    if the cap is hit before the model emits end_turn.

    on_end_turn, if given, validates the model's end_turn text: it returns None to
    accept (the loop returns the text) or a correction string to inject as a user
    message, re-prompting the model instead of returning. This keeps a leader that
    ends its turn conversationally (e.g. after reply_operator) from being mistaken
    for a final artifact. Bounded by MAX_END_TURN_CORRECTIONS.
    """
    logger = logging.getLogger(agent_id)

    # Initialize the backend's conversation state for this agent run.
    # Each ModelBackend instance is single-use per conversation.
    backend.begin(system=system, initial_message=initial_message)

    # True when operator messages were injected at the end of the previous
    # iteration; we capture the model's next text response as the reply.
    _pending_operator_reply = False
    _end_turn_corrections = 0

    for _ in range(max_iterations):
        # Send the current conversation state to the model and get its next action.
        response = backend.complete(model=model, tools=tools or None, max_tokens=max_tokens, temperature=temperature)

        if on_model_response is not None and response.text:
            on_model_response(response.text, response.stop_reason)

        # Surface the model's conversational reply to an operator injection.
        # Only capture text from tool_use responses — end_turn text is the artifact JSON.
        if _pending_operator_reply and on_operator_reply and response.stop_reason == "tool_use":
            text = (response.text or "").strip()
            if text:
                on_operator_reply(text)
        _pending_operator_reply = False

        if response.stop_reason == "end_turn":
            text = response.text or ""
            # Let the caller veto a premature/invalid end_turn and re-prompt instead
            # of returning — e.g. a leader that ended conversationally without finish().
            if on_end_turn is not None and _end_turn_corrections < MAX_END_TURN_CORRECTIONS:
                correction = on_end_turn(text)
                if correction is not None:
                    _end_turn_corrections += 1
                    logger.debug("end_turn rejected (%d): %r", _end_turn_corrections, text[:120])
                    # Record the rejected assistant turn first so history stays a valid
                    # alternating sequence, then add the correction as a harness message
                    # (NOT inject_user_message — this is not operator input).
                    backend.record_assistant_message(text)
                    backend.append_harness_message(correction)
                    continue
            # The model is done — it produced a final text response (the artifact).
            logger.debug("end_turn: %r", text[:120])
            return text

        if response.stop_reason == "max_tokens":
            # Output budget exhausted mid-response — the result is unusable.
            raise RuntimeError(f"{agent_id}: model hit max_tokens before completing")

        # stop_reason == "tool_use": the model made progress — reset the end_turn
        # correction budget so it applies only to consecutive stuck end_turns.
        _end_turn_corrections = 0

        # Execute each requested tool, collect results.
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
