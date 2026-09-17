# PROJECTS

Status: **design** · Scope: in-memory implementation (persistence deferred — see [§7](#7-deferred--delicate-discussions))

A **PROJECTS** layer sits on top of the existing single-engagement pipeline. It organizes
many engagements under named projects, runs several of them live at once (bounded), and
gives each project its own private ensemble catalog.

---

## 1. Overview

- When you open Athena you land on a **PROJECTS** layout (VS Code-like).
- A **PROJECT** groups multiple **ENGAGEMENTS**. One project → many engagements.
- Projects are listed on the **left** (~25%). Selecting one shows its engagements on the
  **right** (~75%).
- Engagements are **rows** on the right pane. A row shows a **progress bar with a percent
  inside it** and the **name of the specialist currently acting**. Rows animate live as the
  engagement progresses.
- Engagements **within the same project** can share the artifact outputs of other
  engagements in that project.

### Project operations

- **Create** — give it a name + (optionally) a private ensemble directory.
- **Rename**.
- **Delete** — with a confirm.
- **Zip / export** — password-protected. (Deferred — see [§7](#7-deferred--delicate-discussions).)

Project names **must be unique** and match `^[A-Za-z0-9_.-]+$` (alphanumeric, underscore,
dash, dot). The name is used as the on-disk directory name, so it is also validated against
path traversal (`.` / `..` / separators rejected beyond the character class).

### New project (UX)

Creating a project is just: **a name** + **an ensemble directory**. The ensemble directory is
that project's **private ensemble catalog** — a place for ensembles that must not live in the
shared global catalog. It may start empty; engagements can still use the global catalog.

Once a project is selected you can **create** and **delete** engagements within it.

### Engagement row states

```
queued → briefing (awaiting plan) → running → awaiting-you (gate) → running → done
                                                                          ↘ rejected / abandoned
```

- **queued** — created and asked to run, but no concurrency slot free yet.
- **awaiting-you** — a plan/committee/loop gate is blocking on an operator decision. The row
  must surface this so the operator knows *which* of several live runs needs attention.

---

## 2. Scope & decisions (this iteration)

Explicit decisions taken during design:

1. **Concurrency: bounded, never unbounded.** Several engagements run live, capped by a
   semaphore (default small, e.g. 2–3). Excess run requests **queue**, they are not rejected.
2. **Engagements stay in-memory** — like today. No engagement database yet. Reconstructing
   engagement records from disk is a deliberate later conversation ([§7](#7-deferred--delicate-discussions)).
3. **The only durable state is the project directory + its metadata.**
   Projects survive a restart by scanning the projects directory; engagements do not.

### Non-goals (for now)

- Durable engagement history / resume-after-restart.
- Password-protected zip export.
- Multi-user / multi-operator. Still a **single operator**, now driving several concurrent runs.

---

## 3. Architecture — backend

### 3.1 `Engagement` and `Project` as first-class objects

Today an "engagement" is smeared across three places in
[`runner.py`](../src/athena/server/runner.py): the `EngagementContext` dataclass (state), the
large `_run` closure plus handler closures inside `start_engagement()` (behavior), and the
module-level `_executor` / `_active` globals (lifecycle). The doc's ask — *"the Engagement
object should be modified to operate on its own"* — becomes:

- **`Engagement`** — a class owning its `EngagementContext`, its handler methods
  (`_ask_user_handler`, `_gate_handler`, `_loop_gate_handler`, …, lifted out of the closure),
  its own worker thread, and a reference to the shared run-concurrency semaphore. It belongs
  to exactly one `Project`.
- **`Project`** — name, private-ensemble-catalog path, created-at, and an in-memory
  `dict[run_id, Engagement]`. Mirrored on disk as a directory ([§3.4](#34-data-model--the-disk-line)).
- **Registry** — replaces the flat module-global `_active: dict[run_id, EngagementContext]`
  with `projects: dict[name, Project]` (each holding its engagements). `run_id` stays globally
  unique so the existing SSE-by-`run_id` routing is untouched.

This refactor is the enabling first step; everything else builds on it.

### 3.2 Concurrency — semaphore + thread-per-engagement (not a fixed pool)

Do **not** model the bound as `ThreadPoolExecutor(max_workers=N)`. An engagement holds its
worker thread for the *entire* time an operator takes to decide a gate — minutes, parked on a
`threading.Event`, not CPU. A fixed pool of N would let N gate-blocked runs **starve** the
pool so a new engagement couldn't even start briefing.

Instead:

- **One daemon thread per engagement** (they are I/O- and gate-bound, not CPU-bound).
- **A `run_semaphore` of size N** caps how many engagements may be *actively executing*.
  `is_busy()` ([runner.py:161](../src/athena/server/runner.py#L161)) — today a boolean gate —
  becomes this capacity gate.
- Over-capacity "Run" requests set the row to **queued** and auto-start when a slot frees.

Per-run state is already isolated (per-`EngagementContext` events, per-run backends,
per-run artifact dir, SSE routed by `run_id`) — see the roadmap already written in the
[runner TODO](../src/athena/server/runner.py#L48-L56). The blockers it names are exactly the
two things this doc addresses: a multi-run UI/operator model, and turning `is_busy()` into a
capacity gate.

### 3.3 Event / SSE model

The event path already works: pipeline threads → PyPubSub → [`_bridge`](../src/athena/server/bus.py#L61)
→ a per-`run_id` `asyncio.Queue` → SSE ([events.py](../src/athena/server/routes/events.py)) →
the UI reduces it. Three concrete changes are needed for the projects view:

1. **Fan-out: multiple listeners per run.** [`bus.create_queue`](../src/athena/server/bus.py#L40)
   currently does `_queues[run_id] = q` — it **overwrites**, so a run can feed only one open
   stream. The moment an animating row *and* a drilled-in dashboard both watch the same run,
   one goes dead. Change `_queues[run_id]` to a **set of queues**; `_bridge` fans out to all.
2. **Fan-in: one `EventSource` per running engagement.** [`useEvents`](../src/ui/src/useEvents.js#L12)
   opens exactly one stream for one run today. The projects view opens **N** (one per live
   row). With bounded N this needs *no* new backend endpoint — an aggregate per-project stream
   is unnecessary at this scale.
3. **Late-join snapshot.** Events are dropped when no queue is registered
   ([bus.py:68](../src/athena/server/bus.py#L68)); only terminal state is synthesized on
   reconnect. Each `Engagement` keeps a small **in-memory progress snapshot** (current
   committee, percent, active specialist, awaiting-decision flag). A row reads it once over a
   plain `GET` to render *before* connecting, then goes live on SSE. This also feeds rows that
   are visible but not yet streamed.

### 3.4 Data model & the disk line

```
workspace/                # runtime store — ATHENA_SRV_PROJECTS_DIR (default), gitignored.
  <project-name>/         # NOTE: distinct from the repo's tracked projects/ docs directory.
    project.json          # {name, created_at} — durable metadata
    ensembles/            # this project's PRIVATE ensemble catalog (0..n ensemble dirs)
      <ensemble-name>/    #   a self-contained ensemble (manifest.yml, committees/, schemas/…)
    artifacts/
      <run_id>/           # engagement outputs (B5 relocates them here)
```

- **Durable (disk):** the project directory, `project.json`, the private ensemble catalog,
  and artifact outputs. On startup, **scan the projects root** (`ATHENA_SRV_PROJECTS_DIR`,
  default `workspace/`) to rebuild the in-memory project list.
- **In-memory (ephemeral):** the `Project` → `Engagement` registry and all live engagement
  state.
- **Artifacts move under the project.** The "engagements share artifacts within a project"
  feature *requires* artifacts to be project-scoped, so `artifacts/{run_id}/` relocates to
  `projects/<name>/artifacts/{run_id}/`. This is already-persistent data — a relocation, not
  new persistence — and it keeps the disk line exactly at "project directories." Read/write
  points to update: [`RunLogger`](../src/athena/artifacts.py#L28), `_read_artifact_fn`
  ([runner.py:276](../src/athena/server/runner.py#L276)), the workflow's `artifacts_dir`
  ([runner.py:355](../src/athena/server/runner.py#L355)), and the artifacts route.
- **Known mismatch (intentional):** artifacts of a completed engagement survive a restart, but
  the in-memory engagement record does not. Reconstructing engagement records from disk is the
  deferred "delicate discussion."

### 3.5 Ensemble resolution — private catalog, then public

`load_ensemble()` and `ATHENA_ENS_PATH` stay **unchanged**. `ATHENA_ENS_PATH` remains the
public ensemble root, exactly as today. Projects add private ensembles on top:

- Each project's `ensembles/` dir is a **private catalog** — 0..n self-contained ensembles,
  each in its own subdir (`manifest.yml`, `committees/`, `schemas/`…).
- When starting an engagement the operator picks an ensemble (or none). Resolution is
  **private-first**: a named ensemble loads from the project's `ensembles/<name>/`; **no name**
  falls back to the public `ATHENA_ENS_PATH` ensemble. A name absent from the private catalog
  raises `EnsembleNotFound` (→ 404) rather than silently running the public ensemble.
- `_resolve_ensemble_path()` ([runner.py:547](../src/athena/server/runner.py#L547)) becomes
  project- and name-aware, but its public branch still returns `Path(ATHENA_ENS_PATH)` — no
  change to the env var's meaning.
- **Note:** the loader re-imports an ensemble's `schemas/` package on every load
  ([loader.py:191](../src/athena/ensemble/loader.py#L191)) and does not cache. Repeatedly
  running the same ensemble across engagements is functionally fine (each run is
  self-contained) but is not deduplicated — acceptable now, worth a cache later.

---

## 4. Architecture — UI

The projects view is largely an **event sink** over the existing machinery, but "just a sink"
hides the real refactor:

- **Per-run reducer state.** [`App.jsx`](../src/ui/src/App.jsx)'s reducer is a **singleton**
  for one run — `engagement`, `committees`, `agents`, `loopGate` are all single-run. The
  projects view needs **N parallel reducer states keyed by `run_id`** (a sub-store per
  engagement). This is the bulk of the front-end work; the SSE plumbing is nearly ready.
- **Layout.** A left project sidebar (create/rename/delete/select) + a right engagement-rows
  pane. Existing components — [`CommitteeGraph`](../src/ui/src/components/CommitteeGraph.jsx),
  the dashboard, the gate/operator modals — are reused for the **drill-in** view of a single
  engagement.
- **Row rendering.** Each row consumes its engagement's progress snapshot ([§3.3](#33-event--sse-model))
  → progress bar + current-specialist label + `awaiting-you` affordance.

---

## 5. Phasing

1. **Refactor** `Engagement`/`Project` objects + registry (out of the `runner.py` closures/globals).
2. **Backend multi-run:** `run_semaphore` capacity gate + thread-per-engagement + queued state;
   bus fan-out (set of queues); per-engagement progress snapshot; project dirs on disk +
   startup scan; artifacts relocated under project; ensemble-catalog resolver.
3. **UI:** projects sidebar; per-run reducer state; engagement rows; wire drill-in to the
   existing dashboard.
4. **Deferred** (separate discussions): persistence/resume, password zip.

---

## 6. Concrete change points

| Area | File | Change |
|------|------|--------|
| Engagement/Project objects, registry, semaphore | [`runner.py`](../src/athena/server/runner.py) | Lift closures into an `Engagement` class; `Project` + registry replace `_active`; `is_busy()` → `run_semaphore`; thread-per-engagement |
| SSE fan-out | [`bus.py`](../src/athena/server/bus.py) | `_queues[run_id]` → set of queues; `_bridge` fans out |
| Progress snapshot | [`runner.py`](../src/athena/server/runner.py) + new route | Maintain per-engagement snapshot; `GET` endpoint for late-join |
| Ensemble resolution | [`runner.py`](../src/athena/server/runner.py) | Private-catalog resolver: named → project `ensembles/<name>/`; none → public `ATHENA_ENS_PATH`; unknown name → `EnsembleNotFound` (404) |
| Artifact location | [`artifacts.py`](../src/athena/artifacts.py), [`runner.py`](../src/athena/server/runner.py), artifacts route | Scope under `projects/<name>/artifacts/<run_id>/` |
| Project CRUD | new route module | Create/rename/delete/list projects; name validation |
| UI state | [`App.jsx`](../src/ui/src/App.jsx) | Singleton reducer → per-`run_id` sub-stores |
| UI events | [`useEvents.js`](../src/ui/src/useEvents.js) | One `EventSource` per live engagement |
| UI layout | new pages/components | Projects sidebar + engagement rows; reuse dashboard for drill-in |

---

## 7. Deferred / delicate discussions

These are intentionally **out of scope** for the in-memory iteration and need their own design
pass before implementation:

- **Persistence & resume.** Reconstructing in-memory engagement records from disk after a
  restart (artifacts survive; the engagement record does not). Likely a metadata store
  (SQLite for project/engagement metadata, artifacts staying on disk).
- **Password zip / export.** Bundle a project directory into a password-protected archive
  (standard archive encryption; independent of any at-rest artifact scheme).
