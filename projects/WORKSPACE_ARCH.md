# WORKSPACE_ARCH.md — Workspaces Architecture

Reference: WORKSPACE_UI.md (product design), AGENTS.md (pipeline rules).

---

## Settled decisions

| # | Decision |
|---|----------|
| Frontend | Pure React, lives in `src/ui/` within this repo |
| Graph library | React Flow |
| Concurrency | One engagement at a time |
| Agent termination | Deferred — note placeholder in event hook only (Phase 2) |
| ask_user in server mode | Option B: block pipeline thread on threading.Event; POST /chat unblocks it |
| Server entry point | New top-level `server.py` with `--config` flag pointing to `athena.yml` |
| Artifact serving | Read from disk via new API routes; no database |
| Dev/prod serving | Single server — FastAPI serves built React from `src/ui/dist/`; Vite proxies to FastAPI in dev |
| Unsupported chat target | POST /chat to non-orchestrator agent returns 400 in Phase 1 |
| Tool events | Fired from committee dispatch wrappers, not from `agent_loop.py` — keeps agent loop clean |
| Operator chat with committee leads | Supported via per-agent `queue.Queue` in `EngagementContext`; `run_agent()` drains queue between iterations and injects messages as user turns via `ModelBackend.inject_user_message()` |
| Real-time findings | Recon leader restructured to call `record_observation(observation_json)` tool per classified finding during synthesis; each call fires `agent.finding` immediately; leader emits only `summary` at end |

---

## Overview

Workspaces wraps the existing Athena pipeline in a web service. The pipeline runs
unchanged as a background thread; a new layer instruments it with events and exposes
a FastAPI server that the UI subscribes to.

```
Operator Browser
    │  SSE (pipeline → UI, live events)
    │  HTTP POST (UI → pipeline, chat / engagement request)
    ▼
FastAPI Server  (new: src/athena/server/)
    │  PyPubSub (in-process event bus)
    │  asyncio bridge (call_soon_threadsafe)
    ▼
Pipeline Thread  (existing: orchestrator → committees → tools)
    │  pub.sendMessage() calls  (new: instrumentation added to existing modules)
    ▼
Filesystem artifacts  (unchanged)
```

---

## Component map

### New: `src/athena/server/`

| Module | Responsibility |
|--------|---------------|
| `app.py` | FastAPI application, mounts all routers |
| `routes/engagements.py` | POST /engagements — start a run; GET /engagements/{id} — status |
| `routes/events.py` | GET /engagements/{id}/events — SSE stream |
| `routes/chat.py` | POST /engagements/{id}/chat/{agent_id} — operator message |
| `bus.py` | PyPubSub → asyncio.Queue bridge; one Queue per active engagement |
| `runner.py` | Runs the pipeline in a ThreadPoolExecutor; owns the engagement lifecycle |

### Modified: existing pipeline modules

| Module | Change | Detail |
|--------|--------|--------|
| `agent_loop.py` | New param + message injection | `operator_queue: queue.Queue \| None`; drained between iterations; `backend.inject_user_message()` called for each message |
| `model_backend.py` | New method on all backends | `inject_user_message(text: str)` appends a user turn to `_messages`; implemented on Anthropic, Ollama, Fake |
| `orchestrator.py` | ask_user dispatch made injectable | `run_orchestrator()` accepts `ask_user_handler: Callable[[str], str] \| None`; CLI passes None (stdin), server passes threading.Event handler |
| `orchestrator.py` | pub.sendMessage calls added | engagement.started, engagement.completed, engagement.rejected, orchestrator.question, orchestrator.answer |
| `committees/recon.py` | record_observation tool + dispatch events | Leader gets `record_observation` tool; each call fires `agent.finding` immediately and appends to collected observations; leader emits only `{"summary": "..."}` at end. Dispatch wrappers fire `agent.tool_called` and `agent.spawned` / `agent.spun_down` |
| `committees/planning.py` | Dispatch events only | agent.spawned, agent.spun_down |
| `committees/retrieval.py` | Dispatch events | agent.spawned, agent.tool_called, agent.spun_down |
| `committees/reporting.py` | Dispatch events only | agent.spawned, agent.spun_down |

---

## Event taxonomy (PyPubSub topics)

All topics are dot-namespaced. The UI subscribes to the SSE stream and filters
by topic name on the client side.

```
engagement.started          run_id, target, notes
engagement.completed        run_id
engagement.rejected         run_id, reason

committee.started           run_id, committee
committee.completed         run_id, committee
committee.artifact_emitted  run_id, committee, artifact_path

agent.spawned               run_id, committee, agent_id, title
agent.spun_down             run_id, committee, agent_id
agent.tool_called           run_id, committee, agent_id, tool, input_summary
agent.finding               run_id, committee, agent_id, classification, summary
                            (classification: signal_critical | signal_warn | signal_info | noise | unknown)

orchestrator.question       run_id, question
orchestrator.answer         run_id, answer        (echo after operator replies)
```

`classification` on `agent.finding` drives three visual behaviours:

| classification | color change | notification | node movement |
|---|---|---|---|
| `signal_critical` | immediate red latch | badge (persists, count) | immediate shift toward leader |
| `signal_warn` | yellow latch | badge (persists, count) | gradual shift toward leader |
| `signal_info` | brief yellow flash, returns to base | none | none |
| `noise` | none | none | none |
| `unknown` | brief grey flash, returns to base | none | none |

**Notification badge:** clicking opens a tooltip with the finding `summary`. Each
`signal_warn` increments the badge count. Badge persists until dismissed by operator.

**Node position animation:** `setNodes()` nudges the agent node's `position.y` toward
the leader node on each `signal_warn`. CSS transitions on the node wrapper handle smooth
movement. Movement is capped so the agent never overlaps the leader.

**Orchestrator question:** `orchestrator.question` event → chief orchestrator node shows
a persistent speech bubble with the question text and a "Reply to Question" link.
Bubble does not auto-dismiss. Link opens Operator Chat focused on the orchestrator.

**Inactive committee nodes:** committees not yet started render in a darkened version of
their assigned color (dark-orange for recon, dark-green for planning, etc.).
`committee.started` transitions the node to its full color.

**Artifact criticality (for Artifact Table sort)** is derived from the Pydantic schema
at serve time — no separate field needed:
- `ReportArtifact` → `risk_rating` directly
- `ReconArtifact` → highest `observations[].classification` (signal_warn > signal_info > noise)
- `PlanArtifact` → highest `actions[].priority` (critical > high > medium > low)
- `RetrievalArtifact` → no direct field; see WORKSPACE_TODO.md

---

## Pipeline → UI: SSE

One SSE stream per engagement. The browser opens it when the Dashboard loads.

```
GET /engagements/{run_id}/events
Content-Type: text/event-stream

data: {"topic": "agent.spawned", "committee": "recon", "agent_id": "...", "title": "Network Operator"}

data: {"topic": "agent.tool_called", "committee": "recon", "agent_id": "...", "tool": "http_get", "input_summary": "http://target/robots.txt"}

data: {"topic": "agent.finding", "committee": "recon", "agent_id": "...", "classification": "signal_warn", "summary": "credentials.json exposed at /files/"}
```

### asyncio bridge (bus.py)

The pipeline runs in a thread. PyPubSub fires synchronously on that thread.
`call_soon_threadsafe` pushes events into a per-engagement `asyncio.Queue`.
The SSE handler drains the queue.

```python
_queues: dict[str, asyncio.Queue] = {}   # keyed by run_id

def _bridge(topic=pub.AUTO_TOPIC, **kwargs):
    run_id = kwargs.get("run_id")
    q = _queues.get(run_id)
    if q:
        event = {"topic": topic.getName(), **kwargs}
        _loop.call_soon_threadsafe(q.put_nowait, event)

pub.subscribe(_bridge, pub.ALL_TOPICS)
```

---

## UI → Pipeline: Operator Chat

SSE is one-way. Operator messages go through a regular POST.

```
POST /engagements/{run_id}/chat/{agent_id}
Body: { "message": "focus on port 5432" }

→ 400 if agent_id is not the orchestrator or an active committee leader
```

`EngagementContext` (runner.py) holds two message mechanisms:

```python
class EngagementContext:
    run_id: str
    # Orchestrator ask_user gate (blocking, pre-pipeline)
    reply_event: threading.Event
    pending_question: str | None
    pending_answer: str | None
    # Committee leader queues (non-blocking, injected between iterations)
    agent_queues: dict[str, queue.Queue]   # keyed by agent_id
```

### Orchestrator (ask_user)

`run_orchestrator()` accepts `ask_user_handler: Callable[[str], str] | None`.
Server passes a handler that: sets `pending_question`, fires `orchestrator.question`
via PyPubSub, blocks on `reply_event.wait(timeout=300)`, returns `pending_answer`.
POST /chat writes the answer and sets the event.

Blocking is safe here — `ask_user` only fires before any committees start.

### Committee leaders (mid-run)

Each committee leader's `run_agent()` call receives its `queue.Queue` from
`EngagementContext.agent_queues`. Between every agent loop iteration, the queue
is drained and each message is injected as a user turn via
`backend.inject_user_message(text)`. The model sees operator input on its next
call and can adjust its behaviour accordingly.

POST /chat puts the message into `agent_queues[agent_id]`. If the agent is not
currently running or the agent_id is unknown, returns 400.

---

## Engagement lifecycle

```
POST /engagements          →  create EngagementContext, start pipeline thread
                               fire: engagement.started
                               return: { run_id }

GET  /engagements/{id}/events  →  open SSE stream, drain event queue

[pipeline runs, events stream to UI]

orchestrator.ask_user fires →  orchestrator.question event on SSE
                               UI shows reply prompt in Operator Chat
POST /engagements/{id}/chat    →  unblocks pipeline thread
                               orchestrator.answer event on SSE

[committees run, agent.* events stream]

engagement.completed fires →  SSE stream sends final event and closes
```

---

## Filesystem artifacts

Unchanged. The pipeline continues writing JSON and markdown to
`artifacts/<run_id>/`. The Artifact Table in the UI reads these via:

```
GET /engagements/{run_id}/artifacts          →  list artifact files + metadata
GET /engagements/{run_id}/artifacts/{name}   →  serve file content
```

No database required for Phase 1 of Workspaces.

---

## Deferred (Phase 2+)

- **Agent termination** — `Terminate` button visible in UI but non-functional. The event
  taxonomy includes `agent.spawned` / `agent.spun_down` which are sufficient for the graph.
  Actual cancellation requires cooperative interruption of the agent loop (a stop flag
  checked between iterations) and is a Phase 2 concern.

- **Mid-pipeline operator input gates** — asking the operator between committees (e.g.
  "Recon found critical exposure — continue to Planning?") requires a different pattern
  than the Phase 1 `ask_user` block. Cannot block the pipeline thread at that point.
  Design separately when needed.

- **Pre-flight clarification UI** (Option C) — the cleaner long-term UX for Operator Chat
  before the pipeline starts. Replace Option B threading approach when implemented.
