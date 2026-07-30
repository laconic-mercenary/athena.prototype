# Athena — Code Standards for LLM-assisted Development

Read this before undertaking any non-trivial implementation task. These are
project-specific rules derived from decisions already made and patterns already in
the codebase. They supplement (and sometimes override) general coding instincts.

---

## Before You Write Any Code

1. **Read the file you are about to modify.** Never edit a file you haven't read in
   the current session. The project has evolved significantly; assumptions about
   what's in a file are wrong more often than not.

2. **Read `projects/common/TERMS.md`** if your task involves agent roles, pipeline
   terminology, SSE topics, or ensemble vocabulary. Consistency with those terms is
   mandatory.

3. **Read `projects/common/ARCHITECTURE.md`** if your task touches the SSE bridge,
   operator chat injection, approval gates, or the pipeline thread.

4. **Read `projects/common/ROADMAP.md`** if you are about to implement something that
   might conflict with a planned architectural change.

5. **Check `projects/WORKSPACE_TODO.md`** for known deferred items before adding a
   workaround for something that is intentionally not implemented.

---

## Python Standards

**Style**
- Follow existing file conventions exactly. This codebase uses type hints throughout,
  `dataclass` for config objects, and Pydantic `BaseModel` for API schemas.
- No `Optional[X]` — use `X | None` (Python 3.10+ union syntax).
- `from __future__ import annotations` is not used; avoid it.

**Schema boundaries: all parameters required**
- In skill yml schemas and ensemble configs, every parameter is required. No optional
  fields. The loader treats parameters as required by default; `required: false` is a
  deliberate exception, not the norm.
- In internal Python code, `T | None` with a `None` default is acceptable where the
  absence is a genuinely meaningful state — not a shortcut to avoid passing a value.

**No backwards-compat shims**
- Do not add `# removed`, `# deprecated`, or dead-code comments for things you deleted.
- Do not keep old function signatures alongside new ones for callers you've already updated.
- Do not use feature flags or `if old_behaviour:` branches. Change the code.

**No premature abstractions**
- Three similar lines are better than a helper that anticipates a fourth.
- Do not design for hypothetical future requirements; build what the task requires.
- If a function will only ever have one caller, inline it unless the logic is complex.

**Error handling**
- Only validate at system boundaries: user HTTP input, external API responses, file I/O.
- Do not add `try/except` inside the pipeline for errors that cannot happen in practice.
- Trust PyPubSub topic dispatch, Pydantic validation (at schema boundary), and the
  agent loop contract. Do not wrap these in additional try/except.
- **No empty or silent catch blocks.** Every caught exception (`except` / `catch`) must
  re-raise, handle meaningfully, or — at minimum — log. Use a **warning** when the failure
  is genuinely safe to ignore (and say why in a comment); an **error** when it is not.
  Never swallow an exception with an empty or comment-only body — a deliberately ignored
  exception still logs at least a `warn` (`console.warn` / `logger.warning`) so it is
  traceable. Applies to Python `except` and JS/TS `catch` alike.

**Comments**
- Default to zero comments. Add one only when the WHY is non-obvious: a hidden
  constraint, a workaround for a specific bug, a subtle invariant.
- Never comment WHAT the code does — the names should do that.
- Never reference the task, the PR, or the caller in a comment.

**Threading**
- The pipeline runs on a background thread managed by `runner.py`.
- `threading.Event` is the correct primitive for approval gates (blocking the pipeline
  thread deliberately). Do not use `asyncio` primitives on the pipeline thread.
- `call_soon_threadsafe` is the only safe way to push events from the pipeline thread
  into the FastAPI event loop. The `bus.py` pattern is the canonical example.
- Do not block the asyncio event loop. All blocking I/O on the server side belongs in
  a thread (via `run_in_executor`) or uses async file I/O.

**Agents**
- `agent_loop.py` is the single source of truth for how an agent runs. Do not replicate
  the loop elsewhere; invoke `run_agent()`.
- `operator_queue: queue.Queue | None` is drained between iterations. Do not drain it
  inside a tool call handler or mid-iteration.
- `on_operator_reply` fires on `stop_reason == "tool_use"`, not `end_turn`. The `end_turn`
  response is the JSON artifact — do not surface it in chat.

---

## FastAPI / Backend Standards

**Routes**
- One router per resource. Do not add routes to `app.py` directly.
- All route handlers are `async def`. Use `run_in_executor` for any blocking call.
- Return `JSONResponse` or Pydantic models — not plain dicts where a schema exists.

**SSE**
- SSE events are JSON objects: `{"topic": "<topic>", ...kwargs}`.
- The topic name must match the exact strings in `TERMS.md` → SSE Event Topic Names.
- `bus.py` handles all bridging. Do not open additional PyPubSub subscriptions in route
  handlers; put new topic handling in `bus.py`.

**Artifacts**
- Artifacts are written to `artifacts/{run_id}/` by the pipeline. The server reads them
  from disk — no database.
- Artifact filenames are fixed: `recon.md`, `plan.md`, `retrieval.md`, `report.md`.
  Do not introduce new artifact filenames without updating `artifacts.py`.

**Configuration**
- `AthenaConfig` and `PlanReviewConfig` in `config.py` are the config entry points.
- New config fields go on these dataclasses. Do not read `athena.yml` keys directly in
  route handlers or pipeline code — always go through the config object.

---

## React / Frontend Standards

**State**
- All global state lives in `useReducer` in `App.jsx`. Do not add local component state
  for data that needs to survive re-renders or be shared across components.
- SSE events dispatch reducer actions. The reducer is the authoritative state machine —
  add new SSE topics by adding a `case` to the reducer, not ad-hoc in the SSE handler.

**No component libraries**
- This project uses vanilla CSS in `index.css`. Do not introduce Tailwind, MUI, Chakra,
  or any component library. Style new elements with the existing CSS patterns.

**No external dependencies without discussion**
- Do not `npm install` a new package to solve a problem that 10 lines of vanilla JS or
  CSS would solve equally well.

**API calls**
- All fetch calls live in `api.js`. Do not call `fetch` directly from a component.
  Add a named function to `api.js` and import it.

**File structure**
- Pages go in `src/pages/`. Components go in `src/components/`. Do not put both in the
  same directory.

---

## Naming Conventions

| Concept | Python name | SSE topic | UI label |
|---|---|---|---|
| Active engagement state | `EngagementContext` | — | — |
| Pipeline event bus | PyPubSub (`pub`) | — | — |
| Finding classification | `signal_critical`, etc. | `agent.finding` | color per ARCHITECTURE.md |
| Individual agent bundle | — | — | Agent Elements |
| Tool skill bundle | — | — | Skills Granules |
| Knowledge package | — | — | Knowledge Granules |
| Pipeline product | — | — | Ensemble |
| User of Athena | operator | — | Operator |
| Top-level agent | orchestrator | — | Chief Orchestrator |
| Phase-level agent | leader | — | Committee Leader |
| Task-level agent | specialist | — | Specialist |

---

## What NOT to Do

- **Do not mock the pipeline in integration paths.** If a test needs to exercise a pipeline
  event, fire it from the actual PyPubSub bus, not a fake one wired only in tests.
- **Do not add agent termination logic** without reading the deferred item in
  `WORKSPACE_TODO.md` — it requires a cooperative stop flag in `agent_loop.py`.
- **Do not hardcode a new approval gate** — the roadmap calls for generalised gates
  (Goal 1). Wire into the existing `EngagementContext` gate pattern.
- **Do not add per-specialist attribution** to artifacts until the deferred item in
  `WORKSPACE_TODO.md` is resolved — the API contract for it is not settled.
- **Do not add a `run_id` to a PyPubSub topic** if it isn't already there — `bus.py`
  uses `kwargs.get("run_id")` to route events to the correct queue.
