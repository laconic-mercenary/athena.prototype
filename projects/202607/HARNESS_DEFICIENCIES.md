# Harness Deficiencies

Deficiencies and improvement areas found reviewing the operator-gate (Architecture X),
graph-hover, and results-copy work. Companion to [[BRIEFING.md]] and [[ENSEMBLE_DEFICIENCIES.md]]
(the latter covers scale/design gaps D1–D8; this file covers implementation defects).

Status legend: **ACCEPTED** (known, fine for now) · **OPEN** (needs decision) · **FIXED** ·
**VERIFY** (needs a live check).

---

## Functional gaps

### H1 — No way to stop an engagement at a committee gate · ACCEPTED (kill the page)
Reject was removed from the committee gate (Accept/Redo only), and nothing replaced it. At a gate
the operator cannot abort — only Accept or Redo (forever). No mid-engagement kill switch exists.
**Decision:** acceptable for the demo — kill the browser tab / restart the container. Revisit with
the global kill switch.

### H2 — Committee gate waits forever → hangs the single worker · ACCEPTED
`_gate_handler` (runner.py) does `gate_decision_event.wait()` with no timeout, and the runner is a
1-worker `ThreadPoolExecutor`. If the operator never decides, that engagement blocks indefinitely
and `is_busy()` stays true, so no new engagement can start until the process restarts.
**Decision:** fine for now (single-operator demo). Future: long timeout + fallback policy (ties to
ENSEMBLE_DEFICIENCIES D7).

### H3 — `awaiting_approval` is overloaded across two phases · OPEN
`ctx.awaiting_approval` is set True for **both** the briefing plan-approval wait and the committee
gate. Two routes guard on it — `plan_review` (approve/reject/revise) and `gate_decision`
(accept/redo) — and neither checks which phase we're in.
**Risk:** a wrong-phase POST (stale browser tab, double-submit) is silently accepted (HTTP 200) but
does nothing, because the code is blocked on the *other* event. The clearest failure: the operator
clicks **Reject** on a stale briefing tab while a committee gate is active → `plan_review` returns
200, the operator believes they stopped the run, but the gate keeps waiting and the engagement
continues. A destructive-intent action silently no-ops. (The reverse — a stale gate POST during
briefing — is defanged by the `clear()`-before-`wait()` in each handler, so it can't auto-fire a
later gate; it just returns a false 200.)
**Direction:** replace the shared flag with a phase enum (or separate `awaiting_plan` /
`awaiting_gate`) so each route 409s outside its phase. Low effort; not yet done.

---

## Correctness / robustness

### H4 — `gate.awaiting_approval` published before `awaiting_approval` set · FIXED
Was: `_await_operator_gate` (workflow.py) published the event, *then* `_gate_handler` (runner.py)
set the flag — a window where a fast POST 409s. In practice unreachable (event delivery is async via
the pubsub→asyncio→SSE bridge while the flag is set synchronously on the next line), but incorrect.
**Fix:** moved the `gate.awaiting_approval` publish into `_gate_handler`, emitted *after* the flag is
set and the event cleared. `GateHandler` now takes `(committee, digest, redo_available)`.

### H5 — Operator chat thread was half-ephemeral · FIXED
`OperatorChat` kept the operator's sent messages in local `useState`, so reopening a leader chat
showed the agent's replies but not the operator's prior messages.
**Fix:** the panel now derives operator messages from the target agent's `messageLog` (the `operator`
entries written by the `OPERATOR_MESSAGE` reducer) — single source of truth, persistent across
reopen.

### H6 — Hovered-node z-index only fixed for committee labels · FIXED
Committee-label tooltips were elevated on hover, but element (winner-badge) and leader (agent) nodes
were not, so a multi-element committee could clip the upper element's "why it won" tooltip.
**Fix:** element and agent nodes now get the same hovered-node `zIndex` elevation.

### H7 — Flow chevrons runtime-unverified · VERIFY
The animated edge chevrons use SVG `animateMotion` + `<mpath href="#edgeId">`, depending on
`BaseEdge` setting `id` on its `<path>` and SMIL resolving it. Compiles; needs an eyeball on a live
run. Also: many SMIL animations on a large graph could get costly (fine at fs-scan scale).

### H9 — A leader ending its turn conversationally crashed the whole engagement · FIXED
Found in live testing: during an operator ↔ leader back-and-forth (ask_operator / reply_operator),
the leader eventually **ended its turn with prose** (e.g. after declining an off-list extension)
without calling `finish()`. The harness treats end_turn as "the final artifact," so
`committee_runner` ran `extract_json()` on the chat sentence → `ValueError` → unhandled →
`engagement.rejected · Internal error`. The operator's next message then 409'd ("not running").
An ordinary conversation could kill the run.
**Fix:** `run_agent` gained an `on_end_turn` validator (bounded by `MAX_END_TURN_CORRECTIONS`).
`committee_runner` supplies one that **re-prompts** ("use a tool: finish / ask_operator /
submit_step") when the leader ends its turn without `finish()`, and also when it finishes with
unparseable artifact JSON — instead of crashing. Refused committees are exempted (they halt).
The re-prompt records the rejected assistant turn (new `ModelBackend.record_assistant_message`)
before appending the correction as a **harness** message (not `inject_user_message`, which would
mislabel it as operator input and, on the OpenAI/Ollama backend, create consecutive user turns).
The post-run `extract_json`+validate is wrapped so the correction-budget-exhausted edge fails as a
clear committee-level error rather than a raw `ValueError`.
**Follow-up (optional):** the fs-scan scan leader playbook says "answer … and stop there," which
invites end_turn; clarifying "never end your turn with plain text — plain text is only ever the
final artifact JSON; call ask_operator to keep waiting" would avoid the extra re-prompt round-trip.

### H8 — Operator Redo shows no attempt count · OPEN (minor)
The operator `gate.decision` passes `attempt: None`, so the back-edge tooltip omits "Attempt N" for
operator-driven redos, unlike orchestrator ones. `retry_counts`/`iterate_counts` are in scope and
could be threaded through.

---

## Polish / cleanup

- **`PlanReviewChat.jsx` dead code** · FIXED — deleted (superseded by `OperatorDecisionModal`).
- **Copy button failed silently** · FIXED — added an `execCommand` fallback + a brief error state.
- **Finding edges used the old animated-dashed style** · FIXED — unified onto the flow-chevron edge.
- **"Redo" only ever maps to `iterate`** (prior shown), never a fresh `retry` · ACCEPTED — known
  single-button tradeoff; if output is garbage the operator can't request a clean-slate redo.
- **No `engagement.approved` for gated committees** · ACCEPTED — a second viewer without the
  optimistic `GATE_RESOLVED` wouldn't see the alert clear (single-operator demo: fine).
