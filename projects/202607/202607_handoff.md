# 202607 Handoff — Ensemble Architecture Design

**Date:** 2026-07-21  
**Status:** Design phase — do not implement ensemble layer code until design is confirmed complete.

---

## Repo layout

Two repos. Both are working directories in Claude Code.

```
athena.prototype/   — Python backend; the running system
  src/athena/       — harness, committees, model backend, schemas, tools
  projects/
    common/         — shared reference docs for coding LLMs (read before any major task)
      TERMS.md          — canonical vocabulary; use these names everywhere
      CODE_STANDARDS.md — threading model, naming conventions, what not to do
      ARCHITECTURE.md   — pipeline diagram, SSE bridge, EngagementContext shape
      ROADMAP.md        — Goal 1 (per-committee holds), 2a (EngagementPlan),
                          2b (dynamic spawning), 3 (ensemble architecture)
    202607/
      ENSEMBLES.md                  — primary ensemble design document (read this first)
      _example/ensembles/           — the concrete red-teaming ensemble example
        red-teaming/1.0.0/
          manifest.yml              — workflow graph, committee wiring, skills registry
          capability.md             — orchestrator-facing: what each committee does
          schemas/                  — Pydantic output contracts, one per committee
          committees/{recon,planning,retrieval,reporting}/
          skills/{9 skills}/

athena.doc/         — documentation and design artifacts
```

**Read before starting:**
1. `projects/common/TERMS.md` — vocabulary is precise; wrong names cause confusion
2. `projects/202607/ENSEMBLES.md` — the full design: vocabulary, compare mode, EngagementPlan, task.md roles
3. `projects/202607/_example/ensembles/red-teaming/1.0.0/manifest.yml` — the concrete example

---

## Design state

### What is settled

**Vocabulary (bottom → top):** Skill → Specialist → Element → Team → Committee → Workflow → Orchestrator

**Element modes:**
- `combine` — different specialists, outputs assembled by leader
- `compare` — same specialist N times at different temperatures; leader selects best
- Compare is SIEM-safe only for reasoning_only elements (no tool calls); never apply to network/web/db elements

**Judge types (compare mode):**
- `leader` — IMPLEMENTED in design; leader receives all N candidates and selects/synthesises
- `scorer` — not yet designed; will raise NotImplementedError
- `agent` — not yet designed; will raise NotImplementedError

**EngagementPlan:** Orchestrator produces structured YAML at end of briefing. Harness reads it to wire approval gates and build per-committee briefs. Existing OrchestratorDialog + Proceed button is the approval UX. Implementation is Goal 2a on the roadmap — not yet built.

**Output contracts:** One Pydantic schema per committee in `schemas/`. Harness validates at committee boundary before passing downstream. On retry, artifact is overwritten.

**Three-layer document schema for committees** (fully applied to recon; apply to others):

| Document | Who reads it | What it contains |
|----------|-------------|-----------------|
| `leader.yml` (system prompt) | Leader at spawn time | Identity, output contract, classification guide, interrupt handling. Short. No operating procedure. |
| `playbook.md` | Leader (injected into initial message) | Element inventory, standard sequencing, when to adapt, what the leader does not do |
| `elements/<id>/task.md` | Leader (injected into initial message) | Assignment template with [VARIABLES], output shape, skills, limitations, adequacy criterion |

**Two-phase leader model:**
- Phase 1 — Leader reads playbook + task cards + engagement brief → submits CommitteePlan JSON
- Phase 2 — Harness executes plan (tasks within a step run in parallel), returns all outputs → leader synthesises final artifact
- The leader never calls summon_specialist directly in the ensemble design; it declares intent, the harness executes

**CommitteePlan structure (agreed, not yet formalised as schema):**
```json
{
  "goals": [
    {
      "id": "g1",
      "description": "...",
      "steps": [
        {
          "id": "g1s1",
          "description": "...",
          "tasks": [
            {"element": "network_scan", "brief": "Scan 10.0.1.0/24, T2 timing, ports 22/80/443"},
            {"element": "web_crawl",    "brief": "Crawl http://10.0.1.5:8080, depth 2"}
          ]
        },
        {
          "id": "g1s2",
          "depends_on": "g1s1",
          "tasks": [
            {"element": "service_probe", "brief": "Probe SSH:22 and TLS:443 on discovered hosts"}
          ]
        }
      ]
    }
  ]
}
```
Tasks within a step are parallel. Steps within a goal are sequential. Goals can depend on other goals.

---

### What is applied vs. still old-style

**Recon committee — fully updated this session:**
- `committees/recon/leader.yml` — rewritten: identity + output contract only; operating procedure removed
- `committees/recon/playbook.md` — NEW: element inventory, standard 3-step sequencing, adaptation rules
- `committees/recon/elements/*/task.md` — all 4 rewritten: assignment template format with [VARIABLES]

**Planning, retrieval, reporting committees — NOT yet updated:**
- `leader.yml` files still embed operating procedure inline (old style)
- No `playbook.md` files yet
- `task.md` files exist but predate the assignment template format
- These need the same treatment as recon before any implementation begins

The recon committee is the reference. Apply the same schema to the other three.

---

## Pending design items

**In priority order:**

1. **CommitteePlan schema** — formalise as Pydantic or YAML schema. The structure is agreed (goals/steps/tasks with depends_on), needs a file. Probably `schemas/committee_plan.py` at the ensemble level or as a harness-level type.

2. **Apply three-layer schema to planning, retrieval, reporting** — each needs a `playbook.md` and revised `leader.yml` and updated `task.md` files using the assignment template format.

3. **EngagementPlan implementation (Goal 2a)** — orchestrator emits structured YAML at end of briefing; `runner.py` reads it to wire gates and build per-committee briefs. Design is in `ENSEMBLES.md`. Not yet built.

4. **Knowledge granules** — explicitly deferred. No design yet. Placeholder in `ENSEMBLES.md` under "Not Yet Designed."

5. **Ensemble registry** — how the orchestrator discovers and selects ensembles. Not yet designed.

6. **Parallel element execution** — elements within a team currently run sequentially in the codebase. True fan-out/fan-in is a Goal 2b prerequisite. Not yet designed at the harness level.

---

## The current codebase vs. the ensemble design

The running system in `src/athena/` pre-dates the ensemble architecture. It hardcodes committees in Python (`committees/recon.py`, `committees/planning.py`, etc.) and wires specialists directly. The ensemble design replaces this with manifest-driven loading — but that implementation has not started.

Do not modify `src/athena/` based on ensemble design decisions until:
1. The three-layer schema is applied to all four committees in the `_example`
2. The CommitteePlan schema is formalised
3. The EngagementPlan implementation plan is confirmed

The `_example` directory is purely design artifact for now. The harness that reads it does not exist yet.

---

## Key constraints to remember

- **compare mode** is only safe for `execution: reasoning_only` elements. Never apply it to network_scan, service_probe, web_crawl, web_retrieval, db_retrieval — these would generate N× traffic and trigger SIEM.
- **Foundation-Sec** (`foundation-sec-8b` via Ollama) cannot call tools. Security fine-tuning broke function calling. Never wire skills to the threat_analysis element.
- **Back-edge on retry**: committee artifact is overwritten, not appended.
- **Orchestrator is harness-level**: not part of any ensemble; selects and loads ensembles; reads `capability.md`; never reads `task.md`.
- **task.md is committee-internal**: only the committee leader reads it. The orchestrator reads `capability.md`.
