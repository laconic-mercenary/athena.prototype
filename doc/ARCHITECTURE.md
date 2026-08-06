# Athena — Architecture Reference

Describes the settled patterns a coding session needs to understand before touching
the server, harness, or frontend. Read alongside the source files for full detail.

---

## System Overview

```
Operator Browser
    │  GET  /engagements/{id}/events      — SSE stream (harness → UI)
    │  POST /engagements/{id}/chat/...    — operator message injection (UI → leader)
    │  POST /engagements                  — start engagement
    │  POST /engagements/{id}/gate        — committee gate decision (accept / redo)
    │  POST /engagements/{id}/loop-gate   — in-loop gate decision (step / element / tool)
    ▼
FastAPI Server  (src/athena/server/)
    │  PyPubSub ALL_TOPICS subscription  (bus.py)
    │  asyncio.Queue per engagement      (bus.py)
    ▼
Harness Thread  (blocking, ThreadPoolExecutor, max_workers=1)
    │  harness/orchestrator.py → harness/workflow.py → harness/committee_runner.py
    │  pub.sendMessage() calls throughout
    ▼
Filesystem artifacts  (artifacts/{run_id}/)
```

---

## Harness Execution Model

The harness runs on a **blocking background thread** managed by `runner.py` via a
`ThreadPoolExecutor(max_workers=1)` — one engagement at a time.

```
Harness thread:
  harness/orchestrator.py         (two-phase: briefing → workflow)
    └─ Phase 1: plan briefing     blocks thread on ctx.reply_event (threading.Event)
    └─ Phase 2: workflow.py       drives the workflow graph node by node
         └─ committee_runner.py   runs one committee; dispatches elements in parallel
              └─ agent_loop.py    drives one specialist agent (tool calls, iteration cap)
              └─ pub.sendMessage(agent.*, step.*, task.*, committee.*)

FastAPI event loop (async, main thread):
  bus.py ← pub.ALL_TOPICS ← harness thread
  call_soon_threadsafe → asyncio.Queue → SSE endpoint → browser
```

---

## SSE Bridge (`bus.py`)

PyPubSub fires synchronously on the harness thread. `bus.py` bridges it to the async
event loop without blocking either thread.

```python
_queues: dict[str, asyncio.Queue] = {}   # keyed by run_id
_loop: asyncio.AbstractEventLoop          # captured at server startup

def _bridge(topicObj=pub.AUTO_TOPIC, **kwargs):
    run_id = kwargs.get("run_id")
    q = _queues.get(run_id)
    if q:
        event = {"topic": topicObj.getName(), **kwargs}
        _loop.call_soon_threadsafe(q.put_nowait, event)

pub.subscribe(_bridge, pub.ALL_TOPICS)
```

The SSE endpoint (`routes/events.py`) opens a `Queue` for the engagement and drains it
as `data: {json}\n\n` chunks in a `StreamingResponse`.

---

## Operator Chat Injection

The operator can send messages to any committee leader mid-run:

```
POST /engagements/{run_id}/chat/{agent_id}
Body: { "message": "..." }
```

**How it reaches the leader:**
1. `runner.py` holds `EngagementContext.leader_queues: dict[str, queue.Queue]`.
2. The POST route puts the message onto the leader's `queue.Queue`.
3. `agent_loop.py`'s `run_agent()` drains the queue between every iteration.
4. Each message is injected as a `user` turn before the next model call.
5. When the leader's next response uses a tool (`stop_reason == "tool_use"`), an
   `agent.operator_reply` SSE event fires with the leader's text.

---

## Gate System

Athena has two gate families:

### Between-committee gates (workflow gates)

Fired by `workflow.py` at each committee boundary. The harness blocks on
`ctx.gate_decision_event: threading.Event`.

```
POST /engagements/{run_id}/gate
Body: { "action": "accept" | "redo", "suggestion": "..." }
```

`gate_decision.py` writes the decision to `ctx` and sets `gate_decision_event`.
The harness reads the action: `accept` advances the workflow; `redo` re-runs the
committee with the operator's suggestion injected into the leader's initial brief.

### In-loop gates (loop gates)

Armed per-committee by the operator via `POST /engagements/{id}/loop-gate/arm`.
Three kinds: `element` (fires after element outputs), `step` (fires after each step),
`tool` (fires before a domain-tool executes). Each kind blocks on
`ctx.loop_gate_event`.

```
POST /engagements/{run_id}/loop-gate
Body: { "action": "accept" | "redo" | "approve" | "deny", ...kind-specific fields }
```

---

## EngagementContext

All mutable state for one active engagement. Lives in `runner.py`. One instance exists
at a time (`_ctx` module-level).

```python
@dataclass
class EngagementContext:
    run_id: str
    status: str                          # "running" | "completed" | "rejected" | "failed"

    # Threading events — one per blocking phase
    reply_event: threading.Event         # briefing phase: operator answers orchestrator
    plan_decision_event: threading.Event # plan review: operator approves/revises plan
    gate_decision_event: threading.Event # committee gate: operator accepts or redoes
    loop_gate_event: threading.Event     # in-loop gate: operator decides per step/element/tool

    await_phase: str                     # AWAIT_NONE | AWAIT_REPLY | AWAIT_PLAN | AWAIT_GATE | AWAIT_LOOP

    leader_queues: dict[str, queue.Queue]        # keyed by agent_id
    armed_gates: dict[str, set[str]]             # committee → {"element","step","tool"}

    # Set once the workflow starts
    orchestrator: OrchestratorHarness | None
    ensemble: LoadedEnsemble | None

    # Briefing phase state
    pending_question: str | None
    pending_answer: str | None
    plan_decision_type: str | None       # "approve" | "revise"
    revision_message: str | None

    # Committee gate state
    gate_decision_action: str | None     # "accept" | "redo"
    gate_decision_suggestion: str | None
    gate_committee: str | None
    gate_digest: str | None

    # In-loop gate state
    loop_gate_decision: dict | None

    # Specialist disable (forward-only, per compound key)
    disabled_specialists: set[str]

    # Set by abort_engagement()
    cancelled: bool
```

---

## Component Map

### Backend: `src/athena/server/`

| Module | Responsibility |
|--------|----------------|
| `app.py` | FastAPI app factory; wires all routers |
| `bus.py` | PyPubSub → asyncio.Queue SSE bridge |
| `runner.py` | `EngagementContext`, `ThreadPoolExecutor`, gate helpers |
| `manifest.py` | `serialise_ensemble()` — JSON-safe ensemble for the UI |
| `routes/engagements.py` | `POST /engagements`, `GET /engagements/{id}` |
| `routes/events.py` | `GET /engagements/{id}/events` (SSE) |
| `routes/chat.py` | `POST /engagements/{id}/chat/{agent_id}` |
| `routes/plan_review.py` | Plan approval: multi-turn Q&A + plan decision release |
| `routes/gate_decision.py` | Committee gate: accept / redo + collaborator co-approval |
| `routes/loop_gate.py` | In-loop gate: step / element / tool decisions |
| `routes/artifacts.py` | `GET /engagements/{id}/artifacts/{committee}` |
| `routes/report_chat.py` | Post-engagement debrief LLM chat |
| `routes/collaboration.py` | Collaborator email thread + reply webhook |
| `routes/specialist_config.py` | Manifest summary + specialist enable/disable |

### Backend: `src/athena/harness/`

| Module | Responsibility |
|--------|----------------|
| `orchestrator.py` | Two-phase run: briefing dialogue → workflow dispatch |
| `workflow.py` | Drives the workflow graph; fires committee gates |
| `committee_runner.py` | Runs one committee; dispatches elements/specialists |
| `skill_executor.py` | Resolves and executes skill implementations |

### Backend: `src/athena/ensemble/`

| Module | Responsibility |
|--------|----------------|
| `loader.py` | Parses `manifest.yml` into `LoadedEnsemble` |
| `types.py` | `LoadedEnsemble`, `LoadedCommittee`, `LoadedElement`, `LoadedSpecialist` |

### Frontend: `src/ui/src/`

| File | Responsibility |
|------|----------------|
| `App.jsx` | Global state (`useReducer`), SSE connection, routing |
| `api.js` | All fetch calls to FastAPI (single source of truth) |
| `index.css` | All styles (single file, no component library) |
| `pages/EngagementRequest.jsx` | Start page — submit engagement instructions |
| `pages/OrchestratorDialog.jsx` | Briefing: plan review + committee tree |
| `pages/Dashboard.jsx` | In-run: committee progress, gate dialogs |
| `components/CommitteeGraph.jsx` | React Flow graph of agents |
| `components/CommitteeTree.jsx` | Accordion tree: committees → elements → specialists |
| `components/OperatorDecisionModal.jsx` | Committee gate dialog (Review + Up Next tabs) |
| `components/OperatorChat.jsx` | Mid-run chat with any leader |
| `components/ReportChat.jsx` | Post-engagement debrief |

---

## SSE Event Taxonomy

Topic strings are the contract between harness and frontend. Use the exact strings below.

```
# Engagement lifecycle
engagement.completed
engagement.rejected
engagement.aborted
engagement.approved
engagement.plan_revision
engagement.collaborator_pending

# Orchestrator briefing phase
orchestrator.question
orchestrator.answer
orchestrator.message

# Committee lifecycle
committee.started
committee.completed
committee.ask_operator
committee.operator_replied
committee.result_selected

# Step / task granularity (in-loop)
step.started
step.completed
step.superseded
task.started
task.completed

# Agent lifecycle
agent.spawned
agent.spun_down
agent.tool_called
agent.tool_result
agent.model_text
agent.operator_reply
agent.failed

# Gate
gate.redo_unsupported

# Collaborator thread
collaborator.operator_message
collaborator.replied
```
