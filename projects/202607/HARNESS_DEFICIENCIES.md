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

---

## In-loop gate family (element / tool / step) — see [[HARNESS.md]]

Found in a one-over of the in-loop gate build (element/tool/step gates + UI + briefing switches),
before live testing. Ranked P1–P10 at review time.

### H10 — Element gate modal shows variant labels but not their outputs · FIXED (P1)
The gate payload stripped each variant's `output` (only `label`/`title` reached the UI), so the
operator was asked to confirm/override the winner **without seeing what each variant produced** —
picking blind on the leader's rationale alone. **Fix:** include a truncated `output` per variant in
the `loop_gate.awaiting` payload and render a preview under each choice in the picker.

### H11 — No end-to-end test of the tool/step gate wiring · FIXED (P2)
The pure helpers (`_apply_tool_gate`/`_apply_step_gate`) and the route/channel were tested, but
nothing exercised `spec_dispatch` actually calling the tool gate through a real specialist run.
**Fix:** added an integration test that runs `_run_one_specialist` with the tool gate armed (approve
→ skill executes; deny → denial in the tool result), and repaired the stale `LoadedSpecialist`
fixtures (`title`/`skill_ids`) in `tests/test_committee_runner.py` en route.

### H12 — Step-gate "redo" re-runs everything and spends the step budget · OPEN (P3, skipped)
On redo the step already executed (specialists ran, tools fired, `step.completed` published) and
`step_count` was already incremented, so the leader resubmitting **re-runs all tasks (re-executes
tools) and consumes another step** against `max_steps` — a couple of redos on a low-`max_steps`
committee can hit the cap. Deliberately not fixed yet; redo isn't free. Future: either don't count a
redone step, or snapshot/replay without re-executing side-effecting tools.

### H13 — Concurrent tool gates require re-clicking the header chip per specialist · OPEN (P4)
Compare mode runs specialists in parallel; the lock serializes them into N sequential prompts, but
each decision does `setLoopGateOpen(false)`, so specialist 2..N only surface as the header chip and
must be re-opened by click. Kept as-is pending a look at the live UI. Likely fix: auto-open the modal
on each new `loop_gate.awaiting`.

### H14 — A denied tool call burned the specialist's only tool-call budget · FIXED (P5)
`_tool_calls_made` was incremented before the gate check with `SPECIALIST_MAX_TOOL_CALLS = 1`, so a
deny left the specialist unable to act at all. **Fix:** count only **executed** (approved) calls
against `SPECIALIST_MAX_TOOL_CALLS`; a denial no longer consumes it, so the specialist may propose a
different action. Bounded by a new total-attempts ceiling `SPECIALIST_MAX_TOOL_ATTEMPTS` (executed +
denied) to prevent a prompt storm from a model that ignores the "you may stop" hint.

### H15 — Element "Re-select" showed a suggestion box that was silently dropped · FIXED (P6)
The element modal's Redo→"Re-select" opened the suggestion textarea, but the element gate ignores a
suggestion, so the text went nowhere (and cost two extra clicks). **Fix:** suppress the
suggestion-confirm step when the modal is a choice picker (`choices` present) — Re-select is one click.

### H16 — `await_phase` not reset if the gate handler raised mid-wait · FIXED (P7)
Theoretical (nothing in the critical section currently throws), but a raise between setting
`AWAIT_LOOP_GATE` and resetting would leave a stale phase. **Fix:** `try/finally` resets the phase.

### H17 — Briefing arm is a per-committee loop with no rollback · OPEN (P8, minor)
Arming pre/post at briefing loops `loopGateArm` over every committee; a mid-loop failure leaves some
armed and some not (plus an error toast). Recoverable by re-toggling. Low likelihood.

### H18 — Briefing arming keys by committee name; a later plan revision could orphan it · OPEN (P9)
`armed_gates` is keyed by the `plan.committees` names captured at arm time; a revision that renamed a
committee would orphan the arm. Revisions rarely rename committees, so low.

### H19 — `step.completed` fires before the step gate · ACCEPTED (P10)
On redo the graph briefly shows the step completed, then a new step appears. Cosmetic.

---

## Briefing / plan-revision robustness (found live testing the switch panel)

### H20 — A malformed `submit_plan` crashed the whole engagement · FIXED
`run_briefing` did `dict(tc.input.get("plan", {}))` **outside** the try/except. When the
model passed `plan` as a bare string (common on plan *revisions*), `dict("…")` raised
`ValueError: dictionary update sequence element #0 has length 1; 2 is required`, which
propagated to `_run` → `engagement.rejected · Internal error` — the run died silently while
the operator waited at the briefing panel. **Fix:** coerce defensively before validating —
`str` → `json.loads`; anything not a `dict` gets a re-prompt result ("plan must be a JSON
object … resubmit") instead of crashing. Tests in `tests/test_orchestrator_briefing.py`.

### H22 — SSE `onerror` killed auto-reconnect → UI froze mid-run · FIXED
Live: the run hung on "gate · awaiting decision after report" even though the operator
approved it — the backend logs showed `Gate 'report' → advance (Operator accepted)` and the
run completing, but the UI never updated (and then 409'd on `loop-gate-arm`). Root cause was
**client-side**: `useEvents.js` did `es.close()` in `onerror`, which defeats `EventSource`'s
built-in auto-reconnect. After any transient SSE hiccup the client went permanently deaf —
it had received the "gate awaiting" event, then the stream errored, and it never saw the
subsequent `gate.decision` / `engagement.completed`. **Fix (two parts):** (1) `onerror` no
longer closes — it lets the browser auto-reconnect, and the client closes only when it
*receives* a terminal event; (2) `events_stream` now re-emits terminal state on connect
(SSE has no replay), so a client reconnecting after the run finished learns it immediately
instead of hanging on heartbeats. Also fixed the empty `catch` in `onmessage` (now logs).
Tests in `tests/test_loop_gate.py` (terminal-replay). **Note:** intermediate events lost
during a disconnect gap are still not replayed (bus.py is non-persistent) — only terminal
state is reconciled; full replay/`Last-Event-ID` is a larger future item.

### H23 — Long blocking tool call + non-replayed SSE gap → operator flew blind · PARTIAL
Live (HTB recon): the model ran `nmap_scan(ports=1-65535, flags=-sV -sC -T2 -O)` — a scan
that takes hours; the skill's 300s `subprocess` timeout bounded each run, but during that
300s the worker is blocked and emits **no events**. The SSE stream dropped in that window and
reconnected (H22), but the `agent.tool_result` and `committee.ask_operator` events fired
**in the gap** and were lost (bus.py is non-persistent — H22's known residual), so the UI
stayed frozen on the `agent.tool_called` ("nmap running") frame and the leader's question
never appeared. With no `--verbose`, the server logs showed only healthcheck `GET /`, so the
operator had no view either. Messaging the leader/orchestrator produced no *visible* result.

**Important correction:** this was NOT a routing/channel bug. Committee `ask_operator` delivery
works (blocks on `operator_queue.get` = `leader_queues[committee]`, fed by `/chat/{committee}`)
and display works (`committee.ask_operator` → `LEADER_QUESTION` renders on the leader's chat).
The failure was purely **observability**: a non-replayed SSE gap + suppressed logs.

**Addressed:** (1) nmap two-phase guidance in `recon/leader.yml` + `nmap_scan/skill.yml` —
forbids `-T0/-T1/-T2` and `-O`, mandates a fast `--min-rate 1000 -T4` discovery pass before
`-sV -sC`, shrinking the blocking window; (2) `--verbose` added to both redteam composes.
**Still open:** intermediate-event replay / `Last-Event-ID` (same root as H22's residual) —
a client reconnecting mid-run still misses gap events; only terminal state is reconciled.

**Cleanup noted:** the `ask_operator_handler(question)` fallback at
[committee_runner.py:889](../../src/athena/harness/committee_runner.py) is dead code —
`operator_queue` is always the committee queue in the workflow path — and it caused a
misdiagnosis. Worth deleting or commenting so the two ask channels aren't confused
(committee → queue; orchestrator → `pending_question`/`reply_event`).

### H24 — No SSE intermediate-event replay on reconnect · OPEN
`bus.py` is non-persistent: it has no event log, so events published while an `EventSource`
is disconnected are lost. The H22 fix stops *permanent* deafness (auto-reconnect restored)
and reconciles *terminal* state on connect, but a client that reconnects mid-run still misses
every event that fired during the gap — as in H23, where `agent.tool_result` and
`committee.ask_operator` were lost during a long blocking scan and the UI stayed frozen.
**Fix (future):** give the bus a small per-run ring buffer of recent events with monotonic
ids, honour the SSE `Last-Event-ID` header on reconnect, and replay anything newer. Makes the
UI fully self-heal mid-run instead of only at terminal state. Larger item than H22.

### H21 — `run_briefing` is an unbounded `while True` · OPEN
[orchestrator.py:302](../../src/athena/harness/orchestrator.py) loops until `submit_plan`
succeeds with no iteration cap (violates the no-infinite-loops standard). If the orchestrator
never submits a valid plan it spins, re-prompting and burning tokens, and no
`engagement.plan_ready` ever fires. The UI switch-panel now self-heals against this (a
`PLAN_REVISION_TIMEOUT` fallback re-enables the panel), but the engagement itself can still
hang. Future: bound the loop (N re-prompts → surface a briefing error).
