# AGENTS.md — Athena

> Standing instructions for any coding agent (Claude Code, Codex, etc.) working in this
> repo. Read the relevant section for your role before making changes. Universal rules
> at the top apply to everyone.

---

## Universal rules — read this regardless of your role

1. **NO offensive / exploit code, ever.** Agents use services exactly as configured.
   No vulnerability exploitation, CVE weaponisation, auth bypass, injection, fuzzing, or
   path-traversal. Recon performs bounded service inventory using normal handshakes and
   metadata reads. **If any requested feature would drift toward offensive capability,
   STOP and flag it — do not build it.**

2. **No dynamic agent spawning, no agent frameworks.** Committees are declared in the
   ensemble manifest. Do not introduce LangGraph, CrewAI, or similar.

3. **Deterministic code wraps the fuzzy LLM.** Sequencing, artifact-schema validation,
   tool scoping, gate logic, and iteration caps are deterministic Python — not behaviors
   we hope the LLM exhibits. The LLM proposes; deterministic logic disposes.

4. **API keys come from environment variables only.** Never hardcode or log keys.

5. **Tool scoping is a security boundary.** Each element gets only the skills declared
   for it in `manifest.yml`. Do not widen an element's skill set without being asked.

---

## Ensemble Developer

You work in `tests/ensembles/<name>/`. Your deliverables are YAML files and Python skill
implementations. You do not touch the harness or the UI.

### Layout

```
tests/ensembles/<name>/
├── manifest.yml              # workflow graph + committee/element declarations
├── capability.md             # capability description shown to the orchestrator
├── committees/
│   └── <committee>/
│       ├── leader.yml        # leader system prompt + model override
│       ├── playbook.md       # optional long-form context injected into the leader brief
│       └── elements/
│           └── <element>/
│               └── <specialist>.yml   # specialist system prompt
├── skills/
│   └── <skill>/
│       ├── skill.yml         # name, description, parameters, returns, side_effect
│       └── impl.py           # deterministic Python implementation
├── schemas/
│   └── <committee>_output.py # Pydantic output schema for the committee
└── requirements.txt          # ensemble-specific deps (installed at server start)
```

### manifest.yml structure

```yaml
name: my-ensemble
version: 1.0.0
workflow:
  entry: <first_committee>
  nodes:
    <committee>:
      output_schema: schemas.<Module>   # imported from schemas/
      transitions:
        - to: <next>                    # advance
        - to: <same>
          condition: retry              # operator triggers full redo
        - to: <same>
          condition: iterate            # operator triggers partial iteration

committees:
  <committee>:
    leader: <committee>/leader.yml
    model: claude-sonnet-4-6
    max_steps: 8
    consumes:
      required: [<prior_committee>]     # artifact dependencies
      optional: [<another>]
    elements:
      - id: <element_id>
        label: Human-readable label
        max_tool_calls: 4               # default: unlimited
        specialists:
          - <committee>/elements/<element>/<specialist>.yml
        skills: [skill_id_a, skill_id_b]

skills:
  - id: skill_id
    definition: skills/<skill>/skill.yml
    impl: skills/<skill>/impl.py::<fn_name>
```

### Specialist YAML (`specialist.yml`)

```yaml
title: Specialist Name
model: claude-haiku-4-5-20251001      # optional; inherits committee default
max_tokens: 4096                       # optional; increase for prose-heavy output
system: |
  System prompt. Be specific about what this specialist does and what it returns.
  It knows only what the leader's brief says — nothing else.
```

### Skill definition YAML (`skill.yml`)

```yaml
name: skill_id
description: >
  One-paragraph description shown to the LLM as the tool description.
side_effect: touches_target | none     # annotate honestly
parameters:
  param_name:
    type: string | integer | boolean | object | array
    description: What the LLM should pass.
    required: false                    # omit for required params
returns: >
  What the function returns, in plain language.
```

### Skill implementation (`impl.py`)

The function receives `**kwargs` matching the parameter names. Return a JSON-serialisable
value. Raise `ValueError` to surface a tool-call error to the specialist.

```python
def my_skill(param_name: str, **kwargs):
    # deterministic implementation — no LLM calls here
    ...
    return {"result": ...}
```

### Pydantic output schema

Each committee's output is validated against its schema before the leader emits it.
Keep schemas strict — required fields only, no `Optional` unless the field is genuinely
absent in some runs.

### Conventions

- Leader YMLs can include `playbook.md` content via `{{playbook}}` in the system prompt.
  The harness injects it automatically when the file exists.
- `max_tool_calls` throttles how many times an element's specialists call tools per step.
  Set it when a specialist has a natural ceiling (e.g. one lookup per source).
- Add `model:` overrides at the specialist level only when a specific capability
  (reasoning, multilingual, etc.) is required. Defaults come from the committee.
- Do not add skills to an element that the specialist's prompt doesn't reference.

---

## Harness Developer

You work in `src/athena/`. Your deliverables are Python modules. You do not write YAML or
touch the UI. The harness must remain correct, auditable, and small.

### Key modules

| Module | Responsibility |
|--------|----------------|
| `src/athena/ensemble/loader.py` | Parses `manifest.yml` into `LoadedEnsemble` typed structs |
| `src/athena/ensemble/types.py` | `LoadedEnsemble`, `LoadedCommittee`, `LoadedElement`, `LoadedSpecialist` |
| `src/athena/harness/workflow.py` | Drives the workflow graph — advances gates, calls `run_committee_with_ensemble` |
| `src/athena/harness/committee_runner.py` | Runs one committee — dispatches elements, collects outputs |
| `src/athena/harness/skill_executor.py` | Resolves skill impls from the ensemble, enforces `max_tool_calls` |
| `src/athena/harness/orchestrator.py` | Wraps the full engagement loop: plan → workflow → reporting |
| `src/athena/server/runner.py` | `EngagementContext`, `start_engagement()`, gate helpers |
| `src/athena/server/app.py` | FastAPI app factory; wires all routers |
| `src/athena/server/bus.py` | SSE event bus — `publish()`, `subscribe()` |
| `src/athena/server/manifest.py` | `serialise_ensemble()` — JSON-safe ensemble for the UI |
| `src/athena/server/routes/` | One file per route group |

### EngagementContext

`runner.py` holds one `EngagementContext` per active engagement (only one can run at a
time). Fields added to the context must be set in `start_engagement()` and reset in the
`RUN_STARTED` path. Do not put mutable defaults on the dataclass — use `__post_init__`.

```python
@dataclass
class EngagementContext:
    run_id: str
    ensemble: LoadedEnsemble | None = None
    disabled_specialists: set[str] = field(default_factory=set)
    # ...
```

### Specialist disable key

Format: `"{committee_name}/{element_id}/{specialist_id}"`. Used in `disabled_specialists`
and by `GET /engagements/{run_id}/manifest-summary` + `POST /engagements/{run_id}/specialist-config`.

### Gate flow

Each committee gate is a `asyncio.Event` stored in `EngagementContext`. The workflow
suspends at the gate; the operator approves via `POST /engagements/{run_id}/gate`;
the event is set and the workflow resumes. Do not add polling or timeouts to this path.

### SSE events

Publish events via `bus.publish(run_id, event_type, payload)`. The UI subscribes on
`GET /engagements/{run_id}/events`. Keep payloads small and JSON-serialisable. Event
type names are `snake_case` strings — the UI pattern-matches on them.

### Conventions

- `run_workflow()` accepts `get_disabled_specialists: Callable[[], frozenset[str]] | None`
  — a lambda that reads `ctx.disabled_specialists` at call time (not a snapshot).
- `SPECIALIST_MAX_TOKENS = 4_096` is the default in `committee_runner.py`. Override at
  the specialist level via `max_tokens:` in the specialist YML. Prose-heavy specialists
  (report writers, narrative generators) need 8192.
- All routes are under `/engagements/{run_id}/...`. Prefix new route groups consistently.
- Do not put business logic in route handlers — call into `runner.py` functions instead.
- `model_backend.py` is the only place that calls the Anthropic SDK directly.

---

## UI Developer

You work in `src/ui/src/`. The UI is a React SPA that connects to the FastAPI server via
REST and SSE. It does not call the Anthropic API directly.

### Key files

| File | Responsibility |
|------|----------------|
| `src/App.jsx` | Root component — holds all state, reducer, SSE subscription |
| `src/pages/OrchestratorDialog.jsx` | Pre-run: plan review + briefing tree |
| `src/pages/Dashboard.jsx` | In-run: committee progress, gate modals |
| `src/components/CommitteeTree.jsx` | `Accordion`, `SpecialistRow`, `CommitteePanel` |
| `src/components/OperatorDecisionModal.jsx` | Committee gate dialog (Review + Up Next tabs) |
| `src/api.js` | All HTTP calls — one named function per endpoint |

### State shape (in `App.jsx`)

```js
{
  run_id: null,
  status: 'idle' | 'running' | 'done' | 'error',
  plan: null,           // EngagementPlan from server
  manifestSummary: null, // serialised ensemble (committees → elements → specialists)
  disabledSpecialists: {}, // { "committee/element_id/specialist_id": true | false }
  events: [],
  // ...
}
```

Reducer actions are `UPPER_SNAKE_CASE`. Add new actions to the reducer in `App.jsx`; do
not manage server-derived state in component-local state.

### Specialist toggle

`handleToggleSpecialist(runId, key, enabled)` in `App.jsx` dispatches `TOGGLE_SPECIALIST`
optimistically and calls `setSpecialistEnabled(runId, key, enabled)` from `api.js`.
On failure it reverts the dispatch. Do not duplicate this pattern in components.

### CommitteePanel / CommitteeTree

`CommitteePanel` is the shared tree renderer used in both `OrchestratorDialog` (editable,
with `onToggleSpecialist`) and `OperatorDecisionModal` Up Next tab (read-only, no
`onToggleSpecialist`). `SpecialistRow` renders a checkbox when `onToggle` is provided,
a static bullet when it isn't.

Do not add state to `CommitteePanel` or `SpecialistRow`. All state lives in `App.jsx`.

### OperatorDecisionModal

Props: `title`, `subtitle`, `body`, `redoAvailable`, `onAccept`, `onRedo`, `onSkip`,
`choices`, `collaboratorEnabled`, `collaboratorPending`, `collaboratorReply`,
`collaboratorThread`, `onSendCollaboratorMessage`, `onCancelCollaboration`,
`nextCommittee`, `plan`, `disabledSpecialists`, `onToggleSpecialist`.

- The **tab bar** only renders when `nextCommittee` is non-null. Loop gate modals
  (element / step / tool gates) never receive `nextCommittee` and are unaffected.
- `Footer()` is called as a function (not `<Footer/>`), to avoid remounting the subtree
  on every render and stealing focus from the textarea.
- The collaborator thread lives in `ReviewBody()`, not the footer.

### SSE subscription

`App.jsx` subscribes to `GET /engagements/{run_id}/events` and dispatches reducer actions
based on `event.type`. The SSE connection is managed in a `useEffect` with cleanup. Do
not open additional SSE connections in child components.

### Conventions

- All API calls go through `api.js` — no raw `fetch` in components.
- `plan.committees[name].objective` is an array of strings. `plan.committees[name].steps`
  is an array of step objects. Access both defensively with optional chaining.
- CSS is inline `style={{}}` throughout — no external stylesheet imports.
  Match the existing dark-theme palette (`#0f172a` bg, `#1e293b` border, `#94a3b8` text).
- Do not add new npm dependencies without being asked.
