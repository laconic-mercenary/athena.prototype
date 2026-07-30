# Harness — Gate Architecture

Design notes for the harness's operator-approval gates: the one that ships today (committee),
and the **in-loop gate family** we designed for finer-grained operator control (step / element /
tool-call). Companion to [[BRIEFING.md]] (operator UI surface), [[ENSEMBLES.md]] (harness model),
and [[HARNESS_DEFICIENCIES.md]] (defects). This file is **design** — only the committee gate is built.

Status: **committee gate BUILT** (Architecture X). **In-loop family BUILT** — element,
tool-call (authorization), and post-step gates, backend + UI + tests. Remaining follow-ups
are noted inline (tier-based fail-closed auto-arming; Pace/budget dial; per-committee arming).

---

## 1. Two gate families

There are two structurally distinct places the pipeline can pause for the operator:

| Family | Where it lives | What it gates | Edge-governed? |
|---|---|---|---|
| **Between-committee gate** (built) | `workflow.py`, between committee runs | a committee's *whole output*; drives the next transition | **Yes** — Redo → `iterate`/`retry`, guarded by `_has_declared_transition` |
| **In-loop gates** (design) | `committee_runner.py`, on `tool_dispatch` | a single tool call *inside* a leader's turn | **No** — the decision stays within the leader's turn; no graph traversal |

The committee gate is documented in [[BRIEFING.md]] §10 (Architecture X). This file is about the
**in-loop family**.

---

## 2. The in-loop gate: one mechanism, ride the tool-dispatch block

Key realization: a leader's tools are dispatched **synchronously** by `agent_loop.py`
(`result = tool_dispatch(tc.name, tc.input)` — [agent_loop.py:131](../../src/athena/agent_loop.py#L131)).
The loop does not care whether a dispatch takes 2 ms or 5 minutes. So an in-loop gate is simply:

> **Inside the dispatch of a chosen tool: block on an operator decision, then shape the tool-result
> string from that decision.** The operator's decision reaches the model *as the tool result*.

No changes to `agent_loop.py`. The pause rides the existing synchronous dispatch, exactly as the
committee gate rides `workflow.py`'s loop.

**This is the general form.** Three gates are just *policies* over the same interceptor, keyed by
which tool triggers the pause and what action-vocabulary applies:

| Policy | Trigger tool | Actions | Operator sees | Purpose |
|---|---|---|---|---|
| **Post-step (quality)** | `submit_step` | Accept / Redo(suggestion) / Skip | the finished step digest + suggestion box | review a work product |
| **Element (choice)** | `select_result` | Accept / Override(pick winner) / Redo | candidate list + winner picker | confirm/override a selection |
| **Tool-call (authorization)** | any *side-effecting domain* tool | Approve / Deny(reason) / Pace | the exact call + arguments, **before** it runs | authorize an action before it touches the world |

Because Redo/Skip/Override/Deny all stay **within the leader's turn**, none of them traverses a
graph edge, so the manifest **edge** envelope (`_has_declared_transition`) does not apply. A softer
"is this even gate-able?" envelope does — see §5.

---

## 3. Pre-step vs post-step — resolved

We considered pausing *before* a step (steer intent) vs *after* (review output).

- **Post-step has a natural hook** (`submit_step`) whose result carries the decision → clean, cheap,
  quality-oriented. **This is the step gate.**
- **Pre-step has no hook.** The harness only learns a step boundary exists *at* `submit_step`; the
  leader never announces "I am about to start step N." So a generic pre-step pause is either a blind
  "approve-to-continue" (no visibility into the upcoming step) or requires a new `begin_step(intent)`
  protocol tool. Rejected as a standalone feature.
- **The real pre-step use case is authorization, not symmetry** — "approve this action before it
  touches the target." Its natural home is **the side-effecting tool call itself**, not an abstract
  step. That is the **tool-call gate** (§4), which *is* pre-execution by construction.

Conclusion: build **post-step (quality)** and **tool-call (authorization)** as separate policies;
do **not** conflate them into one "step gate."

---

## 4. Tool-call gate (authorization) — the exploit-committee driver

Motivating scenario: the **exploit committee**, where the operator wants close control over each
action to keep engagement noise under a blue-team detection threshold. There the *action* is the
risk, not the artifact — so the gate must be **pre-execution** and **per-action**.

**This gate is a brake, not a weapon.** It is a human-authorization checkpoint that makes
side-effecting actions *require consent*. It generates no offensive capability; it constrains one.
It only decides whether an already-scoped tool is allowed to fire, when, and how paced — squarely
the charter's "tool scoping is the security boundary" principle, made interactive.

**Actions:**
- **Approve** → dispatch as-is; real result flows back.
- **Deny(reason)** → tool is not executed; the model receives `"operator denied this action:
  <reason>"` and must adapt. **Denial is a first-class outcome, not an error** (see §6).
- **Pace / budget** → the supervised-autonomy dial: *approve-N*, *approve-for-window*,
  *approve-this-call-shape for the rest of the committee*. Turns a per-action gate into a tempo
  control — the operator becomes the pacing authority under a detection threshold without approving
  every single call by hand.
- **Modify (phase 2)** → operator edits arguments before execution (narrow scope, add delay). The
  only action that touches *inputs*; deferred for complexity.

**Audit trail (free):** every gated action + its operator decision is a natural provenance log —
*what* side-effecting action ran, *who* approved it, *when*. In an authorized engagement that is a
headline accountability record, not a byproduct.

---

## 5. Authority & default posture — the manifest envelope returns

The quality/choice gates are opt-in oversight. The tool-call gate is where the safety boundary bites:

- **Gate-able set is declared, not guessed.** A tool's `ToolDefinition` carries a **risk / side-effect
  tier** (e.g. `reads-locally` vs `touches-target`). The gate arms on tools at or above a threshold —
  auditable and explicit, better than a hand-kept per-committee list. This operationalizes
  "tool scoping is the security boundary."
- **Default posture can invert for high-risk committees.** Quality/choice gates default **OFF**
  (opt-in, reactive). A side-effecting tool in the exploit committee can default **ON / fail-closed** —
  the action needs approval unless the operator explicitly arms auto-approve. Fail-closed is the
  correct default for an exploit phase: nothing touches the target unattended.

---

## 6. Denial as a first-class outcome

The H9 lesson (a leader ending its turn unexpectedly must be re-prompted, not crash — see
[[HARNESS_DEFICIENCIES.md]] H9): if the model treats **Deny / Skip** as a hard failure and crashes or
gives up, we have regressed. Requirements:
- The denied-tool result string is clear and actionable.
- The leader/specialist system prompt frames denial/skip as a **normal signal to adapt**.
- A **bounded** retry so the model does not loop forever re-proposing denied actions
  (mirror `MAX_END_TURN_CORRECTIONS`).

---

## 7. Arming — mid-engagement, direct runtime flag (not via the orchestrator)

In-loop gates are **reactive** — the operator arms them after seeing a committee drift (or, for the
exploit committee, arms fail-closed up front). So:

- **Home is the graph view, mid-engagement** ([[BRIEFING.md]] Idea A: control follows into the graph,
  forward-only). Pre-arming at briefing is a secondary offer.
- **Arm via a direct server flag flip**, *not* the orchestrator plan-revision path the briefing
  switches use (§5 there). Arming is a **runtime observation/authorization mode**, not a plan edit —
  no LLM round-trip, no `plan.gates` re-derivation. Instant.
- **Effect is forward-only:** the next matching `tool_dispatch` after the flip pauses; work already
  in flight is untouched.
- **Scope:** per-committee ("gate steps/tools in *this* committee") is more useful mid-run than global;
  global is simpler to start.

---

## 8. Concurrency — nothing new

Reuses the exact cross-thread pattern the committee gate already proved:
- Single-worker `ThreadPoolExecutor`; the block happens **on the worker thread** inside the gated
  dispatch. **No new thread.**
- Decision is a **one-shot rendezvous** → `threading.Event` + decision fields on `EngagementContext`
  (mirroring `gate_decision_event` / `resolve_gate_decision` in `runner.py`). **No new queue** — the
  `leader_queues` operator-chat channel is a *stream*, stays untouched and orthogonal.
- Apply the H4 ordering discipline: `clear()` the Event **before** publishing `awaiting`, so a fast
  resolve cannot be lost.
- **Forces the H3 cleanup.** We would now have *three-plus* await-phases sharing `awaiting_approval`
  (briefing plan, committee gate, in-loop gate). H3 already flags that overloading as a bug risk; an
  in-loop gate makes the **phase-enum refactor a prerequisite** — one Event keyed by an explicit
  await-phase — rather than optional.

Known inherited exposures: **H2** (a gate waits forever → blocks the single worker) applies
identically; during an in-loop pause, operator *chat* to that leader is **queued, not live** (drained
between iterations after dispatch returns) — fine, since the operator acts through the modal.

---

## 9. UI reuse

The `OperatorDecisionModal` ([[BRIEFING.md]] §10) already reserved `showSkip` for exactly this. One
shell, three content variants:
- **Post-step:** suggestion textbox (+ Skip).
- **Element:** candidate / winner picker.
- **Tool-call:** the call + argument display, Approve / Deny(reason), and a Pace/budget control.

Same header, same Accept/primary button, same channel — only the middle content and the
action-vocabulary differ.

---

## 10. Build order — DONE

1. **Element gate (#4)** — BUILT. `_apply_element_gate` on `select_result`; UI winner picker.
2. **Tool-call gate (authorization)** — BUILT. `_apply_tool_gate` wrapping `execute_skill` in the
   specialist's `spec_dispatch`; approve / deny(reason). `LoadedSkill.side_effect` risk tier plumbed
   and surfaced to the operator. **Concurrency:** compare-mode runs specialists in parallel, so the
   runner serializes gate decisions with `loop_gate_lock` (one operator decision at a time).
3. **Post-step (quality) gate** — BUILT. `_apply_step_gate` on `submit_step`; accept / redo / skip.

Shared plumbing: `LoopGateHooks(is_armed, decide)` threaded workflow → committee_runner →
`_run_element` → specialist; `loop_gate.awaiting` / `loop_gate.resolved` events; server channel
`_loop_gate_handler` / `resolve_loop_gate_decision` / `arm_gate`; routes `/loop-gate-decision` +
`/loop-gate-arm`. UI: one `OperatorDecisionModal` shell (picker / suggestion / deny-reason variants)
+ per-kind arm toggles in the graph view. Tests: `tests/test_loop_gate.py`.

**Follow-ups (not yet built):**
- **Tier-based fail-closed auto-arming.** Today arming is operator-driven and gates *every* domain
  tool in a committee when the "tool" gate is on (demoable on fs-scan, whose skills are all
  `reads_local`). The `side_effect` tier is plumbed but not yet used to *auto-arm* high-risk
  committees fail-closed — that needs committee-level risk metadata (D-series).
- **Pace / budget dial** (approve-N / approve-for-window) — the tool gate is approve/deny only so far.
- **Per-committee arming** — the UI toggles arm all committees at once; per-committee is more surgical.
