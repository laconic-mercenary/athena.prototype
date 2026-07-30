# Briefing Page & Operator Control Surface

Design notes for the **Briefing page** (Instructions › Briefing › Engagement) — specifically
the moment the orchestrator presents the EngagementPlan and the operator configures gates and
approves. Companion to [[ENSEMBLES.md]] (harness) and [[ENSEMBLE_UI.md]] (UI rework).

Status: **partially implemented.** Built so far: the 50/50 briefing layout + switch panel
(switches #1/#3 live; #5/#4 disabled) and the operator-authoritative **committee gate** (§10,
Architecture X). Remaining items are design/discussion.

---

## 1. Layout

- Briefing screen splits **50 / 50**: **chat pane** (left) and **Engagement Plan** (right).
- The plan is the **hallmark visual** — the primary object of attention once it is ready.
- Today it is cramped into a fixed 340px right rail (`dialog-ext-pane`) while the finished chat
  dominates a wide screen — the hierarchy is inverted at the decision moment. 50/50 fixes that.
- The **Approve / Request-changes** bar is **sticky** at the bottom of the plan pane so it is
  always reachable regardless of plan length.
- Must be legible to an operator who knows little about the ensemble, yet expressive enough to
  place approval gates and see where intervention may occur.

---

## 2. Operator ↔ Orchestrator control surface

Grounded in the current harness (`workflow.py`, `committee_runner.py`, `orchestrator.py`).
✅ = works today · 🔧 = new harness work.

### A. Gate placement — *where the pipeline pauses for the operator*
| Granularity | Meaning | Status |
|---|---|---|
| Committee transition | Pause after committee X; approve/reject | ✅ `plan.gates: [{after, type: operator_approval}]` |
| Engagement start | Approve plan before anything runs | ✅ the Proceed button |
| Terminal / pre-report | Approve before final artifact accepted | ~ partial (gate on last committee) |
| **Element** (multi-specialist) | Pause after a compare-element's `select_result`; operator confirms/overrides winner | 🔧 new — pause point inside `committee_runner` |
| Step | Pause after each `submit_step` | 🔧 new — likely too granular for a non-expert |

### B. Gate policy — *what a gate does*
- Block until operator acts — ✅ default.
- Notify-but-don't-pause (observe mode) — 🔧 cheap.
- Auto-advance / auto-pause on timeout — 🔧 future (deficiency D7).

### C. Operator-initiated intervention — *any time*
- Message the orchestrator — ✅ · Steer a committee leader (operator interrupt) — ✅
- Halt the engagement (operator-only) — ✅ · Request plan changes before approving — ✅

### D. Ensemble-initiated intervention — *the ensemble asks the operator*
- Leader `ask_operator(...)` — ✅ runtime, **conditional** on `capability.md` guidance.
- Orchestrator `ask_operator` at a gate — ✅ conditional.
- **Surfacing these in the plan needs the orchestrator to annotate the plan with intervention
  points** (or the UI to parse capability.md). The UI does not see capability.md today. 🔧

### E. Orchestrator autonomous decisions — *operator watches, does not place*
- At every committee boundary the orchestrator auto-decides advance / retry / iterate
  ([workflow.py:175](../../src/athena/harness/workflow.py)). Operator does not configure these
  but the plan should make clear they happen.
- Switch #5 below converts these into an operator escalation.

---

## 3. Switch panel (decided)

Toggles a non-expert can flip pre-engagement. **Build: 1, 3, 4, 5 as toggles; 2 via chat for now.**

1. ☐ **Approve at every committee transition** — auto-populates all `after` gates · ✅ cheap
2. ☐ Approve after **[specific committee]** — **via chat for now**, not a toggle yet
3. ☐ **Approve before the final report is delivered** — terminal gate · ✅ cheap
4. ☐ **Approve every multi-specialist element's selection** · 🔧 harness work (element gate)
5. ☐ **Ask me before any retry or iterate** — orchestrator escalation · 🔧 small

Switch #5 is the key mid-engagement lever: today the operator largely engages the orchestrator
**at the end** of the run. #5 creates a decision point *during* the run where the operator can
direct a **retry or iterate**. It requires only that retry/iterate edges be **declared in the
manifest** (fs-scan declares both as self-loops, so #5 is valid there). It does **not** require a
cross-committee back-edge — Task A only extends *how far back* a retry/iterate may reach. See §8
(Safety envelope) for why switch validity must be derived from the manifest.

---

## 4. Task A — iterate/retry back to an earlier committee

**Supported by the engine; gated on manifest declaration + orchestrator awareness.**

1. **Engine ✅** — `retry`/`iterate` carry a `to`; `workflow.py` handles `to != current`
   (back-edge) via `_clear_downstream`.
2. **Manifest 🔧** — the target edge must be declared. fs-scan's `report` declares only
   self-loops (`retry→report`, `iterate→report`); there is **no `report→scan` edge**, so an
   `iterate(to="scan")` at the report gate is undeclared → **defaults to advance** → (report is
   terminal) → engagement completes. Fix: add `- to: scan, condition: iterate` to the report node.
3. **Orchestrator awareness 🔧** — gate context never lists the *legal* `to` targets, so the
   orchestrator guesses target names; a wrong guess silently advances. Inject declared
   transitions into the gate prompt.

---

## 5. Interaction model — DECIDED: everything routes through the orchestrator

**Both toggles and free-form chat reach the plan the same way — via the orchestrator.**

- A **toggle** emits a canned instruction (e.g. "add operator-approval gates at every committee
  transition") down the **same revision path chat already uses**:
  operator action → `inject_revision()` → orchestrator re-submits `submit_plan` →
  `engagement.plan_ready` event → UI renders the new plan
  ([orchestrator.py:365](../../src/athena/harness/orchestrator.py)).
- **Free-form chat** works identically today ("Request changes" → same loop).

**Why this is simpler.** There is **no local plan-draft to reconcile**, so the source-of-truth /
merge problem disappears. The **single source of truth is the orchestrator's plan.** A toggle's
on/off state is **derived from the plan's gates** (the "every committee transition" switch reads
ON iff every committee carries a gate), so once the orchestrator responds the switch simply
reflects the plan. No divergence possible.

**Concurrency guard (decided).** Because each toggle is an async orchestrator round-trip, a second
flip before the first plan returns would race two revisions and desync the (plan-derived) switch
state. So **on any toggle flip, lock the whole switch panel** (disable all switches) until either:
- the next `engagement.plan_ready` event arrives (re-render switches from the new plan), or
- a **~3s timeout** elapses (fallback re-enable, so a dropped/slow response never wedges the panel).

This serializes gate changes — one in flight at a time — and keeps switch state consistent with
the plan. A subtle spinner / dimmed panel signals the brief lock.

**Trade-offs (accepted):**
- **LLM round-trip per toggle** — small latency (masked by the panel lock above), and the
  orchestrator could occasionally mis-apply a structured instruction (non-deterministic).
- **More load on the orchestrator** — every gate change is now an orchestrator turn. This is the
  direct argument for **Idea C** (a dedicated Briefing Orchestrator): route toggles + revisions
  through it and keep the Engagement Orchestrator lean.

(Rejected alternatives, for the record: server-authoritative gate-patch endpoint, and a
UI-held draft merged at "Request changes" — both add a second write path and a merge step this
model avoids.)

---

## 6. Open ideas

### Idea A — control menu follows into the graph view
Carry the gate/intervention config into the **Engagement (graph) view** so the operator can see —
and possibly *add* — gates during the run. Live mutation of `plan.gates` is feasible for
committees **not yet reached** (thread-safe append); gates on already-passed committees are moot.
Forward-only live gating.

### Idea B — plan becomes a progress pane in the graph view
The plan (committee itinerary + gate markers) accompanies into the graph view as a **small,
usually-collapsed pane** that tracks progress (done / active / pending) as the engagement runs.
UI-only, reads existing committee status — low risk. This is the "itinerary" companion to the
live graph.

### Idea C — two orchestrators (briefing vs engagement)
Split the single continuous orchestrator conversation into:
- **Briefing Orchestrator** — Phase 1: gather requirements, produce & revise the EngagementPlan,
  narrate toggles. Ends at approval.
- **Engagement Orchestrator** (graph manager) — Phase 2: gate decisions, retry/iterate, operator
  chat during the run.

**Pros:** bounded contexts (directly mitigates **D1** — unbounded orchestrator context); separation
of concerns; can use different models (briefing = conversational, gate = analytical).
**Cons:** handoff — the engagement orchestrator must be seeded with the approved plan + a briefing
summary; two system prompts to maintain; state transfer. Today it is one `OrchestratorHarness`,
one conversation across both phases.

---

## 7. Scope questions

**Q1 — does switch panel 1–5 answer "where does the ensemble require intervention" (#3)?**
Partially. 1–5 cover **operator-placed** gates plus the retry/iterate escalation (#5) — most of
the *mid-engagement* intervention value. They do **not** surface the ensemble's own **conditional**
`ask_operator` points (category D) — those need plan annotation from the orchestrator. Two distinct
marker types: 🛑 *operator-placed* (deterministic) vs ❓ *ensemble-may-ask* (conditional).

**Q2 — can both toggles and chat update the UI? Ideally everything through the orchestrator.**
Both can update the UI (§5). "Everything through the orchestrator" is cleanest for a single source
of truth but adds load to an already-busy orchestrator (D1). Idea C (two orchestrators) is the
release valve: route toggles + plan revisions through the **Briefing Orchestrator**, keeping the
Engagement Orchestrator lean.

---

## 8. Safety envelope — the manifest is authoritative

**Rule: the manifest.yml is the safety boundary. Neither the operator's switches nor the
orchestrator's decisions may exceed what the manifest declares.** The manifest overrides anything
the orchestrator (or operator) could otherwise request.

**Already enforced for the orchestrator.** An undeclared `retry`/`iterate` target **fails closed**
— [workflow.py:208-216](../../src/athena/harness/workflow.py) logs a warning and defaults to
`advance` rather than traversing an edge the author did not sanction. The set of transitions the
orchestrator may traverse = exactly the manifest's declared edges.

**Consequence for the switch panel — validity is derived from the manifest, not assumed.** Two
classes of switch:
- **Approval gates (pauses)** — #1, #3. A gate is a *pause*, not a graph traversal; the workflow
  honors any `plan.gates` entry regardless of edges. Always safe to place → no manifest backing
  needed.
- **Traversal-gating switches** — #5 (and any future "send work back to committee X"). These gate
  *re-execution*, so they are valid **only if the manifest declares the corresponding
  `retry`/`iterate` edge.** fs-scan declares retry/iterate self-loops → #5 valid. An ensemble with
  no retry/iterate edges → #5 must be **disabled** (fail closed, like #4).

**Therefore the UI needs the manifest's declared transitions per committee** surfaced alongside the
plan — the switch panel renders each traversal-gating switch's availability from manifest
capabilities, defaulting to disabled when the capability is not declared. This upgrades the
"element/graph data is not in the EngagementPlan" gap (§ layout notes) from cosmetic to a **safety
requirement**.

**Smell to fix:** the fail-closed fallback is correct but **silent** (only a log line). If a switch
ever lets the operator request a traversal, an undeclared/undoable request must **surface to the
operator**, not vanish into an `advance`.

---

## 9. Open decisions
- [x] **Source-of-truth for the plan** — DECIDED: everything routes through the orchestrator
  (toggle → revision message → `plan_ready` → UI). Single source of truth = the orchestrator's
  plan; toggle state derives from `plan.gates`. See §5.
- [ ] **Two orchestrators (Idea C)** — PARKED. Revisit when orchestrator load (D1) bites; the §5
  toggle-through-orchestrator decision pushes in this direction.
- [ ] **Surface manifest capabilities to the UI** (declared transitions per committee) so the
  switch panel can validate traversal-gating switches — a **safety requirement**, not cosmetic (§8).
- [ ] **Surface the silent fail-closed fallback** to the operator when a requested traversal is
  undeclared (§8 smell).
- [ ] Element-gate (#4) this pass, or after harness SIT is stable?
- [ ] Annotate plan with ensemble intervention points (needs orchestrator + event work).
- [ ] Add declared cross-committee back-edges to fs-scan to exercise Task A end-to-end.

---

## 10. IMPLEMENTED — committee gate (Architecture X)

The committee operator-approval gate is now **operator-authoritative** (Accept / Redo),
replacing the old approve/reject. At a **gated** committee the operator's decision drives the
transition and the orchestrator's `run_gate` is **skipped**; **non-gated** committees are
unchanged (orchestrator decides). Reject was removed (future global kill switch).

**Flow:** committee finishes → `gate.awaiting_approval` (now carries `digest` + `redo_available`)
→ operator picks **Accept** (→ advance) or **Redo(suggestion)** (→ iterate self, suggestion as
objective note; retry if only retry is declared) → harness emits `gate.decision` tagged
`decided_by: "operator"` (animates the graph) and injects a note so the orchestrator stays
coherent.

**Manifest still governs.** Redo is guarded by the SAME `_has_declared_transition` check the
orchestrator uses — enforced in `_await_operator_gate`, not `run_gate`. `redo_available` is
computed from the declared edges and hides Redo in the UI when undeclared; a stale Redo is
rejected via `gate.redo_unsupported` and the gate re-awaits.

**Files:** `harness/workflow.py` (`_await_operator_gate`, `GateHandler`, gated/non-gated split),
`server/runner.py` (`gate_decision_event` channel, `_gate_handler`, `resolve_gate_decision`),
new `server/routes/gate_decision.py`, `server/app.py`. UI: new reusable
`components/OperatorDecisionModal.jsx` (Accept / Redo, `showSkip` reserved for step reuse),
`api.js` `gateDecision()`, `App.jsx` (`redo_available` in state, `GATE_RESOLVED`), `Dashboard.jsx`
(swap modal, header copy), `index.css` (`.plan-review-btn--redo`). `PlanReviewChat.jsx` orphaned.

**Demo path (no manifest change):** operator flips switch #1 at briefing → gate after `scan` →
`scan` finishes → `OperatorDecisionModal` with Accept/Redo (Redo live, `scan` declares iterate).

**Status:** built; backend imports + full UI build verified. Not yet exercised live (needs the
running app + a gated engagement). Reuses cleanly for the step-level gate (C): same modal + Skip,
same channel, pointed at a step.
