# PROJECTS — build plan

Execution companion to [PROJECTS.md](PROJECTS.md). Ordered, PR-sized tasks grouped into three
milestones. Each task lists **files**, **what**, **acceptance**, and **deps**.

Guiding rule: **Milestone A is a pure refactor with zero behavior change** — the single-run app
must work identically and the existing suite must stay green — so it can land before any of the
risky multi-run work.

Test baseline: `pytest` (see [`tests/`](../tests)). There is **no** runner/server test today —
closest coverage is [`test_artifacts.py`](../tests/test_artifacts.py),
[`test_workflow.py`](../tests/test_workflow.py),
[`test_ensemble_loader.py`](../tests/test_ensemble_loader.py). The refactor below should **add**
`tests/test_registry.py` / `tests/test_runner.py` since it introduces the first real seams.

---

## Milestone A — object refactor (no behavior change)

Lift the engagement out of the `runner.py` closures/globals into real objects, keeping the
single-run behavior and the existing module-level function API intact.

### A1 · `Engagement` class
- **Files:** [`runner.py`](../src/athena/server/runner.py) (→ likely split into
  `athena/server/engagement.py`)
- **What:** Move `EngagementContext` fields plus the `_run` / `_ask_user_handler` /
  `_gate_handler` / `_loop_gate_handler` / `_is_gate_armed` / `_read_artifact_fn` closures into
  an `Engagement` class. The class owns its context, its handlers (now methods), and its worker
  thread. The module-level `start_engagement`, `reply_to_orchestrator`, `resolve_approval`,
  `resolve_gate_decision`, `resolve_loop_gate_decision`, `arm_gate`, `send_to_leader`,
  `get_manifest_summary`, `render_artifact`, `set_specialist_enabled`, `send_to_orchestrator`,
  `abort_engagement`, `get_context` become **thin wrappers** delegating to the registry +
  engagement.
- **Acceptance:** full suite green; a manual single run behaves identically (briefing → plan
  gate → committees → gates → report).
- **Deps:** none.

### A2 · `Project` + `Registry`
- **Files:** new `athena/server/registry.py`; [`runner.py`](../src/athena/server/runner.py)
- **What:** `Project` (name, private-ensemble-catalog path, created_at, `dict[run_id,
  Engagement]`) and a `Registry` holding `dict[name, Project]`. Replace the module global
  `_active`. For A, use a **single implicit "default" project** so no external behavior changes
  yet. `get_context(run_id)` searches across projects.
- **Acceptance:** suite green; `run_id` still globally unique (SSE routing untouched).
- **Deps:** A1.

### A3 · Refactor safety net
- **Files:** new `tests/test_registry.py`
- **What:** unit tests for registry add/lookup/remove, `Engagement` lifecycle transitions, and
  the delegating wrappers. Locks in behavior before Milestone B changes it.
- **Acceptance:** new tests pass; coverage on the new seams.
- **Deps:** A1, A2.

---

## Milestone B — backend multi-run

### B1 · Concurrency: semaphore + queued state
- **Files:** [`runner.py`](../src/athena/server/runner.py), `registry.py`,
  [`engagement_status.py`](../src/athena/engagement_status.py)
- **What:** Replace the boolean `is_busy()` ([runner.py:161](../src/athena/server/runner.py#L161))
  with a `run_semaphore` (size N, config default 2–3). Each engagement runs on **its own daemon
  thread** (already per-engagement after A1) and acquires the semaphore to *execute*; if none
  free, the engagement enters a new **`QUEUED`** status and auto-starts when a slot frees.
  Remove the `RuntimeError("An engagement is already in progress")` path.
- **Acceptance:** start 3 engagements with N=2 → two run, one shows `QUEUED`, then starts when
  one finishes. No pool starvation when runs are parked on gates.
- **Deps:** A1, A2.

### B2 · Bus fan-out (multiple listeners per run)
- **Files:** [`bus.py`](../src/athena/server/bus.py), [`events.py`](../src/athena/server/routes/events.py)
- **What:** `_queues[run_id]` → **`set` of queues**. `create_queue` adds; `remove_queue`
  discards by identity; [`_bridge`](../src/athena/server/bus.py#L61) fans out to every queue for
  that `run_id`.
- **Acceptance:** two concurrent `EventSource`s on one run both receive all events; closing one
  doesn't kill the other.
- **Deps:** none (independent; can land early).

### B3 · Per-engagement progress snapshot + GET
- **Files:** `engagement.py`, new route `athena/server/routes/progress.py`
- **What:** Each `Engagement` maintains a small snapshot `{status, percent, current_committee,
  active_specialist, awaiting: {kind, committee} | null}`, updated where it already publishes
  events. Add `GET /engagements/{run_id}/progress`. Percent derivation: committees
  completed / total from the plan (coarse is fine).
- **Acceptance:** GET returns correct live state mid-run; a row can render before opening SSE.
- **Deps:** A1.

### B4 · Project directories + CRUD + startup scan
- **Files:** new `athena/server/projects_store.py`, new route
  `athena/server/routes/projects.py`, [`app.py`](../src/athena/server/app.py)
- **What:** On-disk layout per [PROJECTS.md §3.4](PROJECTS.md#34-data-model--the-disk-line):
  `projects/<name>/project.json` + `ensembles/` + `artifacts/`. Routes: `POST /projects`
  (create), `GET /projects` (list), `PATCH /projects/{name}` (rename), `DELETE /projects/{name}`
  (confirm-guarded). **Name validation** `^[A-Za-z0-9_.-]+$` + reject `.`/`..`/separators.
  Startup: scan `projects/` to hydrate the registry.
- **Acceptance:** create/rename/delete round-trip on disk; invalid names 4xx; projects survive a
  server restart; engagements do not.
- **Deps:** A2.

### B5 · Relocate artifacts under the project
- **Files:** [`artifacts.py`](../src/athena/artifacts.py) (`RunLogger`),
  [`runner.py`](../src/athena/server/runner.py) (`_read_artifact_fn` @276, `artifacts_dir` @355),
  artifacts route [`routes/artifacts.py`](../src/athena/server/routes/artifacts.py)
- **What:** `artifacts/{run_id}/` → `projects/<name>/artifacts/{run_id}/` everywhere. Thread the
  project through the engagement so all four read/write points resolve the project-scoped path.
- **Acceptance:** a run writes/reads artifacts under its project; the "share within project"
  read path can see sibling engagements' outputs; [`test_artifacts.py`](../tests/test_artifacts.py)
  updated and green.
- **Deps:** A2, B4.

### B6 · Private-catalog ensemble resolver
- **Files:** [`runner.py`](../src/athena/server/runner.py#L547) (`_resolve_ensemble_path`),
  `engagement.py`
- **What:** Resolver takes `(project, ensemble_name)` and searches the project's `ensembles/`
  **first**, then falls back to the public `ATHENA_ENS_PATH` root (semantics unchanged, per
  [PROJECTS.md §3.5](PROJECTS.md#35-ensemble-resolution--private-catalog-then-public)). Engagement
  start carries the chosen ensemble name.
- **Acceptance:** an ensemble in `projects/<name>/ensembles/foo/` loads for that project; absent
  it, the public `ATHENA_ENS_PATH` ensemble loads; unknown name → clear 4xx.
- **Deps:** A2, B4.

### B7 · Project-scoped engagement endpoints
- **Files:** [`routes/engagements.py`](../src/athena/server/routes/engagements.py)
- **What:** `POST /projects/{name}/engagements` (create + optionally run, with ensemble name),
  `DELETE …/engagements/{run_id}`, list engagements for a project. Drop the single-run 409.
- **Acceptance:** multiple engagements coexist under a project and across projects; delete works.
- **Deps:** B1, B4, B6.

---

## Milestone C — UI

### C1 · Per-run reducer state
- **Files:** [`App.jsx`](../src/ui/src/App.jsx)
- **What:** The reducer is a **singleton** for one run today (`engagement`, `committees`,
  `agents`, `loopGate`). Refactor into **per-`run_id` sub-stores** — a map of engagement states,
  each reduced independently from that run's events. Biggest front-end change.
- **Acceptance:** two runs' states update independently with no cross-talk.
- **Deps:** B2 (fan-out helps but not required for distinct runs).

### C2 · Projects sidebar
- **Files:** new `pages/Projects.jsx`, new `components/ProjectSidebar.jsx`,
  [`api.js`](../src/ui/src/api.js)
- **What:** VS Code-style left pane (~25%): list/select/create/rename/delete (confirm) wired to
  the B4 routes.
- **Acceptance:** CRUD from the UI; selection drives the right pane.
- **Deps:** B4.

### C3 · Engagement rows
- **Files:** new `components/EngagementRow.jsx`, `pages/Projects.jsx`,
  [`useEvents.js`](../src/ui/src/useEvents.js)
- **What:** Right pane rows: progress bar with percent inside + current-specialist label +
  `awaiting-you` affordance. Each row reads the B3 snapshot once, then goes live via **one
  `EventSource` per running engagement** (update `useEvents` to support N independent streams).
- **Acceptance:** rows animate live; a `QUEUED` row shows queued; an awaiting row flags for
  attention; reconnect restores state from the snapshot.
- **Deps:** B3, B7, C1.

### C4 · Drill-in to the existing dashboard
- **Files:** [`Dashboard.jsx`](../src/ui/src/pages/Dashboard.jsx),
  [`CommitteeGraph.jsx`](../src/ui/src/components/CommitteeGraph.jsx), modals
- **What:** Selecting a row opens the existing single-engagement dashboard bound to that
  `run_id`'s sub-store — reusing `CommitteeGraph`, gate/operator modals as-is.
- **Acceptance:** drill-in shows the full graph + gates for the selected run; back returns to the
  rows.
- **Deps:** C1, C3.

---

## Sequencing summary

```
A1 → A2 → A3
        ├─→ B1 ─┐
        ├─→ B4 ─┼─→ B5, B6 ─→ B7
B2 (independent)─┘
        └─→ B3
C1 → C2, C3 (needs B3/B7) → C4
```

Suggested PR cut points: **A1+A2+A3** (refactor), **B2** (fan-out, standalone), **B1+B3**
(concurrency + snapshot), **B4+B5+B6+B7** (projects on disk + ensembles + endpoints),
**C1+C2**, **C3+C4**.

---

## Open items to confirm before/while building

- **Semaphore default N** (2 or 3?) and whether it's an env var (`ATHENA_SRV_MAX_CONCURRENT_RUNS`).
- **Percent model** — committees-done/total is the cheap default; confirm that's good enough for
  the row, or whether steps-within-committee granularity is wanted.
- **Create-vs-run** — does creating an engagement auto-run it, or is "Run" a separate action on
  the row? (Plan assumes create can optionally run; row has an explicit run for queued/manual.)
