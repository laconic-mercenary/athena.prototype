# SKILLS_TOGGLE — operator tool enable/disable at briefing

Status: **design / ready to implement**
Date: 2026-08-05

## Goal

In the briefing view (`OrchestratorDialog`), give the operator a panel listing the ensemble's
skills/tools with per-tool enable/disable toggles. Disabling a tool **actually removes it from
the toolset handed to the agents for this engagement** — conveying (and enforcing) tighter
control over deviations from the execution the model proposes.

## Locked decisions

1. **Real enforcement** — a disabled skill is pruned from every specialist's toolset at runtime;
   agents cannot call it.
2. **Flat global list** — one deduplicated list of all ensemble skills. A toggle affects that
   skill everywhere it is used (all committees / specialists).
3. **Briefing only, locked at proceed** — toggles are editable while the engagement is awaiting
   plan approval (`AWAIT_PLAN`); once the operator approves the plan, the set is applied and
   frozen for the run.

## UX

- New **Tools** panel in the briefing side pane, a sibling of `BriefSwitchPanel`
  ([OrchestratorDialog.jsx:132](../../src/ui/src/components/../pages/OrchestratorDialog.jsx#L132)).
- Flat list of skills; each row: name + a small `network` tag when `side_effect: touches_target`
  (the on-the-wire tools — the deviations most worth clamping), and an on/off toggle.
- All tools enabled by default.
- Panel locks (read-only) once the plan is approved.
- Optional nicety (not required v1): a one-line hover showing the skill description.

## Data flow

```
briefing (AWAIT_PLAN)
  UI mounts → GET /engagements/{run_id}/skills          → render toggles (all on)
  operator flips a toggle
    → POST /engagements/{run_id}/disabled-skills {ids}   → ctx.disabled_skills = {…}
  operator approves plan
    → POST /engagements/{run_id}/plan-review approve
      → runner.resolve_approval(approved=True)
          → _apply_disabled_skills(ctx.ensemble, ctx.disabled_skills)   ← THE TEETH
          → plan_decision_event.set()                    (only AFTER pruning)
  committees run → specialists built from pruned skill_ids → disabled tools never offered
```

## Backend changes

### `src/athena/server/runner.py`
- `EngagementContext`: add two fields (after the optional block):
  - `ensemble: LoadedEnsemble | None = None` — reference so routes can read the skill list and
    prune it. Set in `start_engagement` where the ensemble is loaded (~line 115).
  - `disabled_skills: set[str] = field(default_factory=set)` — operator's disabled ids.
- `resolve_approval(run_id, approved=True)`: **before** setting `plan_decision_event`, call
  `_apply_disabled_skills(ctx.ensemble, ctx.disabled_skills)` so the workflow can't race ahead of
  the prune. No-op on reject.
- New helper:
  ```python
  def _apply_disabled_skills(ensemble: LoadedEnsemble, disabled: set[str]) -> None:
      if not disabled:
          return
      for committee in ensemble.committees.values():
          for element in committee.elements:
              element.skill_ids = [s for s in element.skill_ids if s not in disabled]
              for spec in element.specialists:
                  spec.skill_ids = [s for s in spec.skill_ids if s not in disabled]
  ```
  (Specialist `skill_ids` is what `committee_runner` actually reads; element list pruned too for
  consistency.) Log the applied set: `_log.info("engagement %s: disabled tools %s", run_id, sorted(disabled))`.

### New route module (or extend `gate_decision.py`, which already has the `/engagements` prefix)
- `GET /engagements/{run_id}/skills` → `200 [{id, name, description, side_effect}]`
  - Read from `ctx.ensemble.skills` (dict `id -> LoadedSkill`; fields: `id, name, description,
    side_effect` — see [types.py:18](../../src/athena/ensemble/types.py#L18)).
  - 404 if no engagement.
- `POST /engagements/{run_id}/disabled-skills` body `{ids: [str]}` → `200 {ok: true}`
  - Guard: `ctx.await_phase == AWAIT_PLAN` (briefing only); else `409 "Tools are locked once the
    plan is approved"`.
  - Validate ids against `ctx.ensemble.skills` keys; ignore unknown ids (or 400 — pick ignore for
    resilience).
  - `ctx.disabled_skills = set(valid_ids)` (replace-whole-set semantics — the UI sends the full set).
- Register the router in `app.py` (unconditional; not gated on collaboration).

## Frontend changes

### `src/ui/src/api.js`
- `getEnsembleSkills(runId)` → GET `/engagements/${runId}/skills`.
- `setDisabledSkills(runId, ids)` → POST `/engagements/${runId}/disabled-skills` `{ids}`.

### `src/ui/src/pages/OrchestratorDialog.jsx`
- New `BriefToolsPanel({ runId, locked })` component near `BriefSwitchPanel`:
  - `useEffect` on `runId` → `getEnsembleSkills` → `skills` state.
  - Local `disabled` set state (all enabled initially).
  - `toggle(id)` → update local set → `setDisabledSkills(runId, [...next])` (fire-and-forget; show
    a transient "updating…" like the switch panel does).
  - Render flat list; `network` tag when `side_effect === 'touches_target'`.
  - `locked` (plan approved / not briefing) → render read-only.
- Mount the panel in the side pane alongside the existing switches. Pass `locked = !awaitingReply
  && planReady`-style condition, or simply lock when `state.page` leaves briefing. Simplest: lock
  when the plan has been approved (engagement left `dialog` page) — the panel only exists on the
  briefing page anyway, so `locked` can track a local "submitting approval" flag.

### CSS (`index.css`)
- Reuse `.brief-switch*` classes for visual consistency; add a `.brief-tool-tag` for the `network`
  chip if needed.

## Edge cases & guards

- **Disabling a critical tool** (e.g. `http_get` needed for OSINT, `http_post` for the RCE path):
  allowed — it's the operator's control. The affected committee may retry/adequacy-fail; that is
  acceptable and on-theme (it demonstrates the clamp). v1 does **not** block this; a future nicety
  is to show which committees use each skill so the impact is visible.
- **Replace-whole-set** semantics avoid add/remove races: the UI always sends the complete disabled
  set; the backend stores it verbatim.
- **Locking**: `POST /disabled-skills` is rejected after `AWAIT_PLAN`, so a late toggle can't take
  effect mid-run (matches "briefing only").
- **Prune ordering**: prune before `plan_decision_event.set()` so no specialist is built from an
  un-pruned list.
- **Isolation**: each engagement loads its own `LoadedEnsemble` instance
  ([runner.py:115](../../src/athena/server/runner.py#L115)), so mutating its skill lists affects
  only this run.

## Out of scope (v1)

- Per-committee granularity (decided: flat global).
- Live mid-run toggling (decided: briefing only).
- Persisting the disabled set across a restart of the same engagement.

## Rebuild

Backend (`runner.py`, new route, `app.py`) + UI → requires `./stop && run.sh`. The ensemble
manifest is untouched, so no ensemble reload concerns.
