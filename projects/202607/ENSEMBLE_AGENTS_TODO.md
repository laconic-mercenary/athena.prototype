# Ensemble Implementation — Agent Working Notes

Personal scratchpad. Updated as implementation progresses. Not a spec — see ENSEMBLES.md.

---

## Phase 0 — Harness foundation

- [ ] Replace/rewrite `src/athena/` to match new design — treat existing code as freely overwritable
- [ ] Manifest loader: parse `manifest.yml` → EngagementPlan-compatible structure
  - [ ] Resolve `output_schema: schemas.ClassName` via `schemas/__init__.py` in ensemble root
  - [ ] Parse `consumes` block (currently missing from Phase 0 loader description in ENSEMBLES.md — minor doc gap)
  - [ ] Parse `transitions` (including self-loops with `condition: retry` / `condition: iterate`)
  - [ ] Derive terminality from absence of forward edges (NOT `transitions: []` — design changed)
- [ ] Skill executor: load and run skills from `skills/<name>/impl.py`
  - [ ] `ALLOWED_ROOTS` must be env-var configurable — fs-scan SIT needs `/data` in roots
  - [ ] Execution backend should be pluggable (see D6 in ENSEMBLE_DEFICIENCIES.md for future remote execution)
- [ ] Artifact store: write/read committee outputs to `artifacts/<engagement_id>/<committee>.json`
- [ ] Budget enforcement: Step cap 12 per committee run, iterate 30, global 750 (revised from 200)
  - [ ] Add soft-limit warning at 80% of global budget
- [ ] `schemas/__init__.py` must re-export all output classes — `schemas.ClassName` resolution depends on it

### Known gotchas — Phase 0
- `count_extensions/impl.py` normalisation bug was fixed (ext.lower()) — don't reintroduce
- `ReportOutput.directory` is NOT produced by the `summarize` element — leader must thread it through from ScanOutput. See `committees/report/elements/summarize/task.md` note.
- `_example/` is deprecated — do not use as reference. Use `tests/system/fs-scan/ensemble/` instead.

---

## Phase 1 — Orchestrator (briefing + plan submission)

- [ ] Orchestrator system prompt (see ENSEMBLES.md — Phase 1 tools: `submit_plan`, `ask_user`)
  - [ ] `briefing_required` block in capability.md is a GUIDE, not a hard checklist — orchestrator fills from operator message where possible
- [ ] Load and inject capability.md into orchestrator context at engagement start
- [ ] `submit_plan` tool: validate EngagementPlan schema, return to operator for approval
- [ ] EngagementPlan JSON: `objective` fields are `list[str]`, not plain strings — easy schema mismatch to reintroduce

### Known gotchas — Phase 1
- Phase 1 tools are `submit_plan` and `ask_user` ONLY — no gate tools available yet
- Orchestrator produces EngagementPlan as tool call output, not as a raw JSON message

---

## Phase 2 — Gate loop + committee execution

- [ ] Gate tools: `advance(next_objective?)`, `retry(to, note)`, `iterate(to, note)`, `ask_operator(question)`, `read_artifact(name)`
  - [ ] `retry` and `iterate` support arbitrary lookback — `to` is any previously-visited committee name, not just the immediately previous one. Document this clearly.
  - [ ] `read_artifact` is read-only; not a gate decision signal
- [ ] Leader tools: `submit_step(step)`, `finish()`, `refuse_start(reason)`, `ask_operator(question)`, `reply_operator(message)`
  - [ ] `read_artifact(committee)` granted ONLY when `consumes.optional` is non-empty; rejects names not in that list
- [ ] `consumes` injection:
  - [ ] `consumes.required` → `render_full()` injected into leader's initial message
  - [ ] `consumes.optional` → `render_digest()` injected + `read_artifact` tool granted
- [ ] JIT re-planning: leader emits one `CommitteeStep` at a time — no upfront full plan. Leader sees step result, then emits next step.
- [ ] SSE event taxonomy: must emit all event types defined in ENSEMBLES.md (`engagement.*`, `orchestrator.*`, `gate.*`, `committee.*`, `step.*`, `task.*`, `element.*`, `agent.*`)

### Known gotchas — Phase 2
- Terminality is derived at runtime from absence of forward edges — self-loops on a terminal committee do NOT make it non-terminal
- `condition: retry` and `condition: iterate` are SEPARATE self-loops (Option A — explicit), not combined
- Task-level fan-out within a Step is deferred — tasks run sequentially for now
- Leader prompt `== Loop ==` and `== Operator interrupts ==` sections are static — future optimisation is to inject as a harness header, not templated per-leader

---

## Deferred (post-demo)

From ENSEMBLE_DEFICIENCIES.md:
- **D1** — Orchestrator context windowing (safe at demo scale, ~3–5 committees)
- **D2** — Engagement persistence / checkpointing (currently ephemeral by design; see discussion below)
- **D3** — Mid-flight EngagementPlan revision (partially mitigated by `retry(to)` arbitrary lookback)
- **D4** — Parallel committee execution
- **D6** — Remote skill execution (pivot host support)
- **D7** — Async operator approval / offline digest view
- **D8** — Cross-engagement knowledge store

---

## Open design decisions (record outcomes here)

| # | Question | Decision |
|---|---|---|
| OD1 | D1: simple context cap now or defer? | [TBD — see discussion] |
| OD2 | D2: basic persistence now or ephemeral for demo? | [TBD — see discussion] |
| OD3 | D3: `retry(to)` arbitrary lookback sufficient or need `revise_plan`? | [TBD — see discussion] |
| OD4 | Global Step budget value | 750 (revised from 200) |

---

## SIT green criteria (fs-scan)

GREEN = `ReportOutput` table matches:

| Extension | Count |
|-----------|-------|
| `.py` | 11 |
| `.md` | 4 |
| `.sh` | 3 |
| `.sql` | 3 |
| `.json` | 3 |
| `.yml` | 2 |
| `.html` | 2 |
| `.css` | 2 |
| `.js` | 1 |
| `.csv` | 1 |
| `.txt` | 1 |
| `.toml` | 1 |
