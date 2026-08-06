# 02 — Ensemble Structure

*The point: an **ensemble** is a self-contained, declarative package that defines a whole
engagement pipeline. It is bind-mounted into the harness (`/app/ensemble`) and re-read per
engagement — edit a prompt or a skill and the next run uses it, no rebuild.*

## Layout

```
manifest.yml           # the wiring: committees, elements, skills registry, workflow graph
capability.md          # operator-facing: what the ensemble does + briefing_required
committees/
  <committee>/
    leader.yml         # leader system prompt + model
    playbook.md        # (optional) committee playbook
    elements/<id>/
      <role>.yml       # specialist prompt + model + temperature + max_tokens
      task.md          # default task card for that element
skills/<id>/
  skill.yml            # tool definition (name, description, params, side_effect)
  impl.py              # the implementation (plain Python)
schemas/*.py           # Pydantic output contracts per committee
```

## `manifest.yml` — the wiring
- **workflow** — a graph: an `entry` node + per-committee `transitions` (advance / `retry` /
  `iterate`). Defines committee order and back-edges.
- **committees** — each has a `leader`, `model`, `max_steps`, `consumes` (required/optional upstream
  artifacts), and its `elements`.
- **elements** — `id`, `label` (UI name), `specialists` (list of yml paths), `skills` (which tools
  this element may call), optional `max_tool_calls` (per-element budget).
- **skills registry** — `id` → `definition` (skill.yml) + `impl` (`module.py::function`).

## What guides the models
- **`capability.md`** → drives the orchestrator's briefing. `briefing_required` (e.g. `domain`,
  `scope`) says what to collect; the prose describes each committee at a **capability** level —
  deliberately generic, with no scenario answers baked in (so the briefing doesn't sound scripted).
- **`leader.yml` `system`** → the leader's operating manual: the loop, the standard Step sequence,
  adequacy criteria, `ask_operator` moments, and the exact output JSON.
- **specialist `<role>.yml` `system` + `task.md`** → the worker's narrow instruction: which one tool
  to call and how to report.
- **model / temperature / max_tokens** per agent — e.g. planning runs Claude Haiku + Foundation-Sec
  + Kimi-K3 (three model families), each with tuned budgets.

## How tools (skills) are defined
`skill.yml`:
- `name`, `description` (the model reads this to decide *when* to call it), `parameters`
  (JSON-Schema), `returns`, and **`side_effect`**: `reads_local` (default, harmless) or
  `touches_target` (goes on the wire — surfaced to the operator's tool gate).

`impl.py`: a plain function returning a dict. Skills are self-contained.

The harness turns each *granted* skill into a `ToolDefinition` for the specialist's agent loop. A
specialist can only call the skills its element lists — nothing else exists in its toolset.

## Output contracts (schemas)
Each committee has a Pydantic schema — `ReconOutput`, `PlanOutput`, `ExploitOutput`, `ReportOutput`.
The leader's `finish()` must emit valid JSON for that schema; the harness validates and re-prompts
on failure. **This is the main rail that keeps free-form model output on track between committees.**

## This ensemble at a glance (`redteam-meridian`)
- **Committees:** recon → planning → exploit → reporting, with one `operator_approval` gate after
  planning.
- **recon elements:** web_osint, github_recon, darkweb_recon, os_check, port_scan, web_enum,
  cve_lookup.
- **planning:** 3 compare analysts — **A** (Claude Haiku), **B** (Kimi-K3, on Modal), **C**
  (Foundation-Sec) — plus a **mitre_mapper** specialist.
- **exploit:** flask_exploiter (*Flask Blood*), redis_operator (*Redis Blood*), shell_operator
  (*Shell Blood*).
- **reporting:** report_writer + mitre_mapper.
- **Live vs baked:** ensemble files (prompts, skills, capability, manifest) are bind-mounted → live
  next engagement. Python `src/` and the UI are baked into the image → need a rebuild.
