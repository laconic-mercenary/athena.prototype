# Ensemble Design — Scale Deficiencies

Deficiencies identified by stress-testing the design against two scenarios:
- **Coding ensemble** — multi-day app/service development
- **Red-team engagement** — full SaaS probe with OSINT, dark web data, and pivoting

Items are ordered by severity. Each is tagged with which scenario surfaces it most acutely.

---

## D1 — Orchestrator context is unbounded in practice
**Affects:** Both scenarios  
**Phase:** Phase 2 (orchestrator runtime)

R4's digest mitigation assumes ~4–5 live committee digests. A 20-committee coding engagement or a multi-stream red-team produces digests + gate rationale that compounds linearly. The orchestrator conversation is continuous and never resets. At engagement hour 8 the orchestrator is reasoning from a heavily compressed context, degrading gate decisions (advance/retry calls) silently with no signal to the operator that quality is slipping.

**Direction:** Orchestrator context windowing — summarise closed-gate history and replace raw digests with a rolling summary beyond a configurable horizon. Alternatively: periodic orchestrator re-initialisation from a durable engagement log.

---

## D2 — No persistence or checkpointing
**Affects:** Coding ensemble (hard blocker)  
**Phase:** Phase 0 (harness infrastructure)

Engagement state lives entirely in-process memory and a flat artifacts directory. A crash, docker restart, or network blip at hour 14 means starting over. There is no checkpoint, no resume, no replay to a prior gate. For anything longer than a single sitting this is a hard blocker. The SSE replay gap in ENSEMBLE_UI.md is the surface symptom; the root cause is there is no durable engagement state store behind it.

**Direction:** Serialise engagement state (plan, gate history, artifact manifests) to a persistent store (SQLite is sufficient) at each gate transition. Runner resumes from the last committed gate on restart.

---

## D3 — EngagementPlan is locked at briefing time
**Affects:** Both scenarios (red-team most acutely)  
**Phase:** Phase 2 (orchestrator)

The orchestrator produces a plan, the operator approves, and the pipeline starts. Mid-flight discovery that changes the approach — a pivot in red-team, a spec change in a coding engagement — has no formal mechanism. The orchestrator can `iterate` a committee with a revised note but cannot add new committees, restructure the workflow graph, or re-brief earlier committees with new information. If dark web data reveals an active breach at a vendor mid-engagement, the correct response is to reorient the entire plan, not iterate one committee.

**Direction:** Add a `revise_plan(patch)` gate tool that allows the orchestrator to amend the active EngagementPlan (add/remove committees, change objectives, reorder transitions) at any gate decision point. The operator re-approves the revised plan before execution continues.

---

## D4 — Sequential committee execution
**Affects:** Both scenarios  
**Phase:** Phase 1–2 (harness + workflow)

OSINT, network recon, web recon, and dark web analysis should run in parallel from engagement start. A coding engagement should run frontend, backend, and database committees simultaneously. The current workflow graph is sequential — one committee at a time. Task-level fan-out within a committee is deferred; committee-level parallelism is not designed at all. For a full red-team this directly multiplies elapsed time by the number of recon streams.

**Direction:** Add `parallel` node groupings to the manifest workflow graph. The harness starts all committees in a parallel group concurrently and waits for all to complete before evaluating the gate that follows the group.

---

## D5 — Global Step budget is too low and too blunt
**Affects:** Both scenarios  
**Phase:** Phase 0 (harness)

200 Steps across the entire engagement sounds generous until you have 15 committees × up to 12 Steps × up to 30 iterations. The ceiling is hit early and halts the engagement with incomplete artifacts. The halt fires as a surprise — there is no warning curve. Per-engagement budget configuration is not designed.

**Direction:** Make budget limits configurable per EngagementPlan (or per-committee). Add a soft-limit warning (e.g. at 80%) that notifies the operator so they can decide whether to expand the budget or terminate cleanly.

---

## D6 — Skill model runs on harness host only
**Affects:** Red-team engagement (hard architectural blocker for pivoting)  
**Phase:** Phase 0 (skill execution model)

All skills currently execute on the harness host. Once a foothold is gained on system A, the next phase requires running tools *from* A to probe B. The harness has no concept of "execute this skill via this pivot host." That is a different execution model entirely — something like an implant, an SSH-proxied tool call, or a C2 channel — that has no representation in the current skill design.

**Direction:** Out of scope for current design phase. Acknowledge this ceiling in the red-team ensemble capability.md. When the harness skill executor is designed (Phase 0), make the execution backend pluggable so a "remote" backend can be added later without changing the skill interface.

---

## D7 — Operator model does not scale to long engagements
**Affects:** Coding ensemble  
**Phase:** Phase 2 (orchestrator + UI)

Every committee boundary is a gate decision. A 20-committee engagement with operator_approval gates, ask_operator calls, and status messages produces a torrent of interactions. The operator cannot be continuously present. There is no async approval model ("approve this gate when you return; pipeline waits"). There is no batched digest view ("here is what happened while you were offline"). The design assumes an engaged operator at every step.

**Direction:** Gate `operator_approval` should support a configurable timeout with a fallback policy (auto-advance, auto-pause, escalate). Add an engagement digest endpoint to the UI so an operator returning after an absence sees a summary of closed gates, not a raw event feed.

---

## D8 — Knowledge does not accumulate across engagements
**Affects:** Coding ensemble  
**Phase:** Phase 0 / post-Phase 2

A coding ensemble that built a service yesterday has no memory of architecture decisions, constraints, or prior conclusions from that session. The knowledge granule design handles within-engagement lookups but nothing persists between runs. For a multi-day engagement this means rediscovering context each session. For red-teaming it means the orchestrator cannot build an evolving picture of the target over time.

**Direction:** Design a cross-engagement knowledge store (separate from per-engagement artifacts). At engagement close, promote selected artifacts to the store. The orchestrator briefing phase can query it to hydrate context before producing the EngagementPlan.

---

## Summary by scenario

| Deficiency | Coding ensemble | Red-team |
|---|---|---|
| D1 — Orchestrator context unbounded | High | High |
| D2 — No persistence | **Blocker** | High |
| D3 — Locked EngagementPlan | High | **Blocker** |
| D4 — Sequential committees | Medium | High |
| D5 — Step budget too blunt | Medium | Medium |
| D6 — Skill host model | n/a | **Blocker** |
| D7 — Operator fatigue | High | Medium |
| D8 — No cross-engagement memory | High | Medium |

Items D1–D5 and D7 are addressable within the current architecture. D6 requires a different execution model and is explicitly out of scope. D8 is a Phase 3+ concern.
