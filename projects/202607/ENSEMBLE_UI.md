# Ensemble UI — Rework Spec

The UI in `src/ui/` was built for the pre-ensemble ("workspaces") architecture. The ensemble
design (see `ENSEMBLES.md`) changed the execution model and the event taxonomy, so the UI needs a
**rework, not a retrofit**. This doc specifies the target UI, categorized by page.

Guiding principle (per the brief): **get the UI correct for the new model — do not preserve a
current feature just because it exists.** Where something is genuinely uncertain, it is listed in
**Open Issues** at the end rather than guessed at.

Reference for all capability names: `ENSEMBLES.md`. **This is Phase 4** in the `ENSEMBLES.md`
Implementation Plan — do it *after* the harness (Phases 1–3), because it consumes the event
taxonomy those phases define. Open Issue #1 (event taxonomy not finalised) is the gating dependency.

---

## 0. Event taxonomy — old vs. new (the foundation)

Everything downstream depends on the events the harness emits over SSE. The current set no longer
matches the model. **The authoritative taxonomy is now `ENSEMBLES.md` → Event Taxonomy (SSE)** —
full topic list + payloads. The table below is the *UI-consumption view* (which surface reads which);
consult ENSEMBLES.md for exact payloads.

**Emitted today** (`grep pub.sendMessage`): `engagement.started/completed/rejected/awaiting_approval/approved`,
`committee.started/completed/artifact_emitted`, `agent.spawned/spun_down/tool_called/finding/operator_reply`,
`orchestrator.question/answer`, plus a one-off `planning.leader.question/answer`.

**Needed for the ensemble model:**

| Area | Event (see ENSEMBLES.md → Event Taxonomy) | Purpose in UI |
|------|--------------------|---------------|
| Briefing | `orchestrator.question` / `.answer` | briefing chat (keep) |
| Briefing | `engagement.plan_ready` | EngagementPlan submitted & validated → activate **Proceed** (replaces text-scan) |
| Lifecycle | `engagement.started/completed/rejected` | keep |
| Committee | `committee.started/completed` | node state (keep) |
| Committee | `step.started` / `step.completed` | **NEW** — the iterative loop; drives the Step timeline |
| Committee | `task.started` / `task.completed` | **NEW** — element invocations within a Step (element activity) |
| Element | `element.candidate` / `element.selected` | **NEW** — consensus (`instances>1`): N candidates + which was chosen + why |
| Findings | `agent.tool_called` | live activity during Steps (keep) |
| Findings | `agent.finding` | criticals/warns; now fired **incrementally at synthesis** (keep mechanism; see R9) |
| Gates | `gate.decision` | **NEW** — orchestrator `advance/retry/iterate/ask_operator` + **rationale** (R2 auditability) |
| Gates | `gate.awaiting_approval` | generalises `awaiting_approval` to *any* `operator_approval` gate |
| Committee digest | `committee.completed` (carries `digest`, `incomplete`) | **NEW** — `render_digest()` + `incomplete` flag at each gate / the digest panel (R4) |
| Operator | `committee.ask_operator` | **NEW** — a leader-initiated question needing an operator reply |
| Operator | `agent.operator_reply` | leader's reply to operator chat (keep; two-way) |
| Halt/budget | `engagement.halted` | **NEW** — halt (operator/budget) fired; artifact `incomplete` |

The **big additions** the UI must surface that have no equivalent today: **Steps**, **Elements/consensus**,
**gate decisions with rationale**, **digests**, and **leader-initiated `ask_operator`**.

---

## 1. Engagement Request (kickoff) — `pages/EngagementRequest.jsx`

Smallest change. The instruction textarea + submit stays; it now kicks off the orchestrator
**briefing → EngagementPlan** flow rather than a direct run.

- **Keep:** textarea (8192 cap), submit, char count.
- **Later (not demo):** ensemble selection (which ensemble/catalog entry). For the demo there is one
  ensemble (`red-teaming`), so no selector — note it as deferred (ties to the ensemble registry).
- No other change.

---

## 2. Briefing & Plan Approval (was `pages/OrchestratorDialog.jsx`)

This page changes the most in *intent*: it is no longer a free chat with a cosmetic panel — it is
**"the orchestrator drafts an EngagementPlan; the operator reviews and approves it."**

- **Keep:** the orchestrator briefing chat (`orchestrator.question`/`.answer`, markdown replies).
- **Remove:** the fake **Techniques / Tools** ATT&CK panel. Its selection is never sent and it
  misrepresents how customization works — the real customization surface is the EngagementPlan
  (per-committee briefs). Delete it; do not port it.
- **Add — the EngagementPlan preview** (the core of this page). When `engagement.plan_ready` fires,
  render the plan for review:
  - The **workflow**: the committees in order, with declared **gates** (e.g. `operator_approval`
    after planning) shown on the transitions.
  - Per committee: **objective / constraints / emphasis**. Mark **downstream objectives as
    provisional** ("refined during the run") — recon's is concrete, the rest are preview-grade.
  - Any operator-requested extras surfaced here (an added gate, a **report-format directive** like
    "MITRE ATT&CK").
- **Proceed = approve the EngagementPlan.** Gate it on `engagement.plan_ready` (structured), not on
  scanning the chat text for "CONFIRM". Operator can still ask for changes in the chat; the
  orchestrator revises and re-emits the plan.

---

## 3. Dashboard / Graph View — `pages/Dashboard.jsx`, `components/CommitteeGraph.jsx`, `SystemView.jsx`, `ArtifactTable.jsx`

The largest rework. The current graph shows a flat `Committee → agents` tree and treats a committee
as a fixed roster. The new model is **hierarchical and temporal**: a committee runs a *loop of Steps*
over *Teams/Elements*, and the orchestrator makes *visible flow decisions* between committees.

### 3a. Committee hierarchy (structure)
Reflect the real hierarchy, not a flat agent list:
`Committee → Team → Element → (Specialist ×N)`.
- **Teams** are the breadth grouping (e.g. a Network Team of `ssh`/`tcp`/`http`/`tls` elements). Render
  a Team as a container of its elements.
- **Elements** are the unit. An element with `instances > 1` (**consensus**) shows the N candidates
  and, once judged, which candidate was **selected** and the one-line **reason** (`element.selected`).
  A single-instance element renders as one node.
- A committee's roster is **not fixed** — elements appear as the leader's Steps invoke them.

### 3b. The Step loop (temporal — this is new)
The committee is a **just-in-time loop of Steps**. Give each active committee a **Step timeline**:
- `step.started`/`step.completed` add Steps as they are planned and run (Step 1: scan + crawl →
  Step 2: probe discovered ports → Step 3: correlate …).
- Within a Step, `task.started`/`task.completed` show the parallel Tasks (element invocations).
- The operator should be able to watch the plan *emerge* — this replaces the illusion of a fixed set
  of agents. Consider a Step rail/timeline beside or under the committee node.

### 3c. Gate decisions (orchestrator flow control — new and important)
Flow is now **LLM-driven within a deterministic envelope (R2)**, and every gate call carries a
**rationale**. Make it visible — this is the auditability payoff:
- On the transition between committees, show the orchestrator's decision: **advance** (proceed),
  **retry**/**iterate** (loop back — draw the back-edge), **ask_operator** (paused for a human).
- Surface the **rationale** (tooltip/inline) so the operator can see *why* the pipeline went the way
  it did. `iterate` count ("attempt N of 30") where relevant.
- `advance` may carry a **refined next-committee objective** — worth showing (the just-in-time
  refinement).

### 3d. Findings (keep — migration only)
The criticals/warns experience carries over (R9): finding cards, the pulsing critical, the header
alert. Requirement is on the harness (fire `agent.finding` incrementally at synthesis; `agent.*`
activity during Steps). UI keeps the current finding-card + header-alert treatment.

### 3e. Digest & artifact panel (`ArtifactTable`)
- Primary view becomes the committee **digest** (from `committee.completed`'s `digest` field —
  `render_digest()`), not raw JSON. The full artifact is available on demand (existing markdown/JSON view).
- **Mark `incomplete: true` artifacts** distinctly (Step cap / halt hit) — an incomplete committee is
  meaningful state (it could not `advance` without operator action, R6b).
- Sort/criticality can key off the digest's adequacy fields (e.g. `risk_rating`, highest
  classification) rather than being derived ad hoc.

### 3f. Operator interaction on the graph
Operator↔committee interaction is now richer (see `ENSEMBLES.md` → Operator Interaction):
- **Chat with a committee leader** (two-way): operator message → leader `reply_operator`. Keep the
  chat surface but make it genuinely two-way (the demo added `agent.operator_reply`; keep it).
- **Leader-initiated `ask_operator`**: a *pending question from the leader* — surface it like the
  orchestrator's question (a persistent prompt with a Reply affordance), not a passive log line.
- **Halt** ("halt & proceed"): an operator control to force the current committee to finish and move
  on (operator-initiated only for now). The resulting artifact carries `operator_directive: advance`.
- **Message typing**: chat vs flow-directive vs steering-hint routes differently (leader vs
  orchestrator). At minimum the UI should let the operator direct a message at the leader (chat/steer)
  vs. the orchestrator (flow) — even if v1 is a simple target toggle.

### 3g. System View (`SystemView.jsx`)
Keep the target-centric view, but update its agent mapping to the new element/team structure. Lower
priority than the committee graph; ensure it doesn't assume the old flat agent model.

---

## 4. Modals & Chats

- **OperatorChat (`OperatorChat.jsx`)** — update to: (a) two-way (render `agent.operator_reply`), (b)
  handle a leader-initiated `ask_operator` (a pending question with a reply box), (c) message typing
  (chat/steer vs flow). It currently only shows the operator's own messages + findings.
- **Gate approval (was `PlanReviewChat.jsx`)** — generalise from "plan review" to **any
  `operator_approval` gate**. It should show the committee **digest** (+ open the full artifact), a
  Q&A against that committee's artifacts, and **approve/reject**. The demo hard-codes it to planning;
  the model allows a gate after *any* committee (e.g. after recon, New2). Reject = engagement starts
  over (existing behaviour).
- **ReportChat (`ReportChat.jsx`)** — keep (post-engagement debrief Q&A over all artifacts).
- **ReportModal (`ReportModal.jsx`)** — keep (view an artifact's rendered markdown). Should handle a
  MITRE-formatted report (freeform sections already accommodate it) and show an `incomplete` banner if
  the artifact is incomplete.

---

## 5. Cross-cutting

- **SSE reliability** — engagements are now longer (loops, gates, retries) and the operator can miss
  events during a disconnect. The pre-existing "no SSE replay on reconnect" gap becomes more painful:
  a refresh mid-run loses graph state, and (worse) loses an `awaiting_approval`/`ask_operator` prompt.
  A per-engagement in-memory event log replayed on connect is now close to required, not optional.
- **State model** — `App.jsx`'s reducer is keyed on `agents`/`committees`. It needs new slices for
  **steps**, **elements/candidates**, **gate decisions**, **digests**, and **pending leader
  questions**. This is a reducer rewrite, not an extension.
- **Deprecated to delete, not port:** the fake Techniques/Tools panel; the assumption that a committee
  has a fixed agent roster; the "CONFIRM"-text-scan approval trigger; anything reading the old
  `committee.artifact_emitted` as the report-ready signal (superseded by digests).

---

## 6. Logging

Three distinct log surfaces. All are developer/debug surfaces — separate from the operator's engagement transcript in the main UI.

### 6a. System log (harness events)
The persistent, viewable record of the SSE event stream. Every event the harness emits — engagement lifecycle, committee transitions, gate decisions, skill executions, budget ticks, errors — is written to this log with a timestamp and structured payload.

- **What it covers:** all `engagement.*`, `orchestrator.*`, `gate.*`, `committee.*`, `step.*`, `task.*`, `element.*`, `agent.*` events (see ENSEMBLES.md → Event Taxonomy).
- **UI:** chronological feed, filterable by event type prefix (e.g. show only `gate.*` or `skill.*`). Should be accessible as a tab or panel alongside the main engagement view — not the default view, but reachable without a page change.
- **Persistence:** survives a page refresh (the harness keeps the log for the engagement lifetime). This is the SSE replay mechanism — reconnecting a client replays the full event log for the active engagement, which also resolves Open Issue #8.

### 6b. Model I/O log (raw LLM interactions)
Every call to a language model: the exact system prompt + messages array sent, and the raw response (text + tool calls). One entry per model invocation, indexed by agent role (orchestrator, committee leader, element), step ID, and task ID.

- **What it covers:** orchestrator briefing calls, orchestrator gate calls, per-step leader calls, per-task element calls.
- **UI:** not shown in the main flow. Accessible via drill-down — clicking a step or task event in the system log opens the model I/O for that specific call. Verbose; primarily for debugging prompt and tool-call issues.
- **Format per entry:** role, model ID, timestamp, token counts (in/out), latency ms, full messages array (collapsible), full response.

### 6c. Operator transcript (distinct from both)
The operator's conversation with the orchestrator (briefing Q&A, gate interactions, `ask_operator` exchanges) is already visible in the main engagement view. This is the *operator-facing* surface — not a debug log. It is not part of the system log or model I/O log.

### Relationship between the three
The system log references model calls by a call ID. The model I/O log stores the full payload indexed by that ID. The operator transcript is a filtered projection of the orchestrator's `question`/`answer` events already in the system log, rendered in the main UI.

---

## Open Issues (unresolved / need a decision)

1. **Event taxonomy** _(RESOLVED)_ — now fully specified in `ENSEMBLES.md` → **Event Taxonomy (SSE)**
   (all topics + payloads; the harness is the authority). The former "single biggest blocker" is
   closed; the UI builds against that list.
2. **Step-loop visualisation.** Timeline rail vs. animating the graph vs. a hybrid. A long/iterating
   committee could produce many Steps — how to keep it legible? Undecided.
3. **Consensus display depth.** Show all N candidates (transparent, but noisy), or just the selected +
   reason with the others on demand? Leaning selected + reason, candidates on click — confirm.
4. **Graph density.** Committee + Team + Element + Steps + gate decisions + findings is a lot on one
   canvas. May need zoom levels (top-level committees ↔ drill into one committee) — the old
   click-to-zoom idea, now load-bearing.
5. **Operator message typing UX.** Simple target toggle (leader vs orchestrator) vs. inferring intent.
   v1 scope unclear.
6. **Gate-decision surface.** Inline on the edge vs. a dedicated "trajectory" panel listing every gate
   decision + rationale (better for audit, more screen real estate). Possibly both.
7. **Provisional-objective UX.** How to visually distinguish "provisional" downstream objectives from
   concrete ones on the plan-approval screen without confusing the operator.
8. **SSE replay** (from Cross-cutting) — decide whether it's in scope for this rework or a fast-follow;
   it materially affects demo robustness for longer engagements.
9. **Incomplete-artifact UX.** How prominently to surface an `incomplete` committee and the fact that
   the orchestrator must retry/iterate/ask rather than advance (R6b) — a blocking banner vs. a badge.
