# Athena — Code Standards for LLM-assisted Development

Read this before undertaking any non-trivial implementation task. These are
project-specific rules derived from decisions already made and patterns already in
the codebase. They supplement (and sometimes override) general coding instincts.

---

## Before You Write Any Code

1. **Read the file you are about to modify.** Never edit a file you haven't read in
   the current session. The project has evolved significantly; assumptions about
   what's in a file are wrong more often than not.

2. **Read `doc/TERMS.md`** if your task involves agent roles, pipeline
   terminology, SSE topics, or ensemble vocabulary. Consistency with those terms is
   mandatory.

3. **Read `doc/ARCHITECTURE.md`** if your task touches the SSE bridge,
   operator chat injection, gates, or the harness thread model.

---

## Python Standards

**Style**
- Follow existing file conventions exactly. This codebase uses type hints throughout,
  `dataclass` for config objects, and Pydantic `BaseModel` for API schemas.
- No `Optional[X]` — use `X | None` (Python 3.10+ union syntax).
- `from __future__ import annotations` is not used; avoid it.

**Schema boundaries: all parameters required**
- In skill YML schemas and ensemble configs, every parameter is required by default.
  `required: false` is a deliberate exception, not the norm.
- In internal Python code, `T | None` with a `None` default is acceptable where
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
- Do not add `try/except` inside the harness for errors that cannot happen in practice.
- Trust PyPubSub topic dispatch, Pydantic validation (at schema boundary), and the
  agent loop contract. Do not wrap these in additional try/except.
- **No empty or silent catch blocks.** Every caught exception must re-raise, handle
  meaningfully, or — at minimum — log. A deliberately ignored exception still logs at
  least a warning so it is traceable. Never use an empty body or comment-only body.
  Applies to Python `except` and JS/TS `catch` alike.

**Comments**
- Default to zero comments. Add one only when the WHY is non-obvious: a hidden
  constraint, a workaround for a specific bug, a subtle invariant.
- Never comment WHAT the code does — the names should do that.
- Never reference the task, the PR, or the caller in a comment.

**Threading**
- The harness runs on a background thread (one `ThreadPoolExecutor` worker) managed
  by `runner.py`.
- `threading.Event` is the correct primitive for all gate types — they block the
  harness thread deliberately. Do not use `asyncio` primitives on the harness thread.
- `call_soon_threadsafe` is the only safe way to push events from the harness thread
  into the FastAPI event loop. The `bus.py` pattern is the canonical example.
- Do not block the asyncio event loop. All blocking I/O on the server side belongs in
  a thread (via `run_in_executor`) or uses async file I/O.

**Agents**
- `agent_loop.py` is the single source of truth for how an agent runs. Do not replicate
  the loop elsewhere; call `run_agent()`.
- `leader_queues` in `EngagementContext` is drained between agent loop iterations. Do
  not drain it inside a tool call handler or mid-iteration.
- An `agent.operator_reply` SSE event fires when `stop_reason == "tool_use"` after an
  operator message injection — not on `end_turn`. The `end_turn` response is the JSON
  artifact; do not surface it in the chat stream.

---

## FastAPI / Backend Standards

**Routes**
- One router per resource group. Do not add routes to `app.py` directly.
- All route handlers are `async def`. Use `run_in_executor` for any blocking call.
- Return `JSONResponse` or Pydantic models — not plain dicts where a schema exists.
- Business logic belongs in `runner.py` or the harness. Keep route handlers thin.

**SSE**
- SSE events are JSON objects: `{"topic": "<topic>", ...kwargs}`.
- Topic names must exactly match the strings in `TERMS.md` → SSE Event Topic Names.
- `bus.py` handles all bridging. Do not open additional PyPubSub subscriptions in
  route handlers. New topic handling goes in `bus.py`.

**Artifacts**
- Artifacts are written to `artifacts/{run_id}/` by the harness. The server reads from
  disk — no database. Artifact filenames are `{committee}.json`.
- Do not invent a new artifact filename or write format without updating the artifact
  routes and the ensemble's output schema.

**Configuration**
- Server configuration comes from environment variables loaded by `dotenv` in
  `server.py`. Do not read env vars directly in route handlers — access them through
  the resolved config values passed into `create_app()` or `runner.py`.

---

## React / Frontend Standards

**State**
- All global state lives in `useReducer` in `App.jsx`. Do not add local component state
  for data that needs to survive re-renders or be shared across components.
- SSE events dispatch reducer actions. The reducer is the authoritative state machine —
  add new SSE topics by adding a `case` to the reducer, not ad-hoc in the SSE handler.

**No component libraries**
- This project uses vanilla CSS in `index.css`. Do not introduce Tailwind, MUI, Chakra,
  or any component library. Style new elements following the existing patterns.

**No external dependencies without discussion**
- Do not `npm install` a package to solve something 10 lines of vanilla JS or CSS
  would solve equally well.

**API calls**
- All fetch calls live in `api.js`. Do not call `fetch` directly from a component.
  Add a named function to `api.js` and import it.

**File structure**
- Pages go in `src/pages/`. Components go in `src/components/`.

---

## Naming Conventions

| Concept | Python name | SSE topic | UI label |
|---------|-------------|-----------|----------|
| Active engagement state | `EngagementContext` | — | — |
| In-process event bus | PyPubSub (`pub`) | — | — |
| Ensemble product | `LoadedEnsemble` | — | Ensemble |
| User of Athena | operator | — | Operator |
| Top-level briefing agent | orchestrator | — | Orchestrator |
| Phase-level agent | leader | — | Committee Leader |
| Task-level agent | specialist | — | Specialist |

---

## Python Module Layout

Every Python module must follow this top-to-bottom order. Mark each section with the
exact comment block below — even if a section is empty, include the header so the
structure is scannable at a glance.

```python
###############
# CONSTS / GLOBALS #
###############

###############
# CUSTOM TYPES #
###############

###############
# CLASSES #
###############

###############
# FUNCTIONS #
###############

###############
# NON PUBLIC FUNCTIONS #
###############
```

**Sections:**

| Section | What belongs here |
|---------|-------------------|
| `CONSTS / GLOBALS` | Module-level constants (`ALL_CAPS`), module-level mutable state, `logger = logging.getLogger(...)` |
| `CUSTOM TYPES` | `TypeAlias`, `TypeVar`, `Protocol`, `NamedTuple`, `TypedDict`, Pydantic models, `dataclass` definitions |
| `CLASSES` | Regular classes that are not pure data types |
| `FUNCTIONS` | Public functions (`def foo(...)`) — callable by other modules |
| `NON PUBLIC FUNCTIONS` | Private helpers (`def _foo(...)`) — internal to this module only |

Imports, `__all__`, and module-level docstrings go above the first section header, in
standard Python import order (stdlib → third-party → local).

---

## What NOT to Do

- **Do not add a `run_id` to a PyPubSub topic** if it isn't already there — `bus.py`
  uses `kwargs.get("run_id")` to route events to the correct queue.
- **Do not add a new gate type by duplicating the existing pattern.** The gate system
  uses `await_phase` and a set of `threading.Event` fields on `EngagementContext`.
  Understand the existing gate flow in `ARCHITECTURE.md` before adding anything new.
- **Do not put blocking calls in async route handlers.** Use `run_in_executor`.
- **Do not write harness state to a database.** `EngagementContext` is in-process and
  ephemeral by design. Artifacts persist to the filesystem only.
- **Do not skip reading `ARCHITECTURE.md`** before touching `bus.py`, `runner.py`,
  or any gate route — the thread model is non-obvious and easy to deadlock.
