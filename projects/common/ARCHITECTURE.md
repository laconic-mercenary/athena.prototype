# Athena — Architecture Reference

Distilled from `projects/WORKSPACE_ARCH.md` and `DEMO.md`. Read alongside the source
files for full detail. This document covers the settled patterns a coding session needs
to understand before touching the server, pipeline, or frontend.

---

## System Overview

```
Operator Browser
    │  GET  /engagements/{id}/events    — SSE stream (pipeline → UI)
    │  POST /engagements/{id}/chat/...  — operator message injection (UI → pipeline)
    │  POST /engagements               — start engagement
    ▼
FastAPI Server  (src/athena/server/)
    │  PyPubSub ALL_TOPICS subscription  (bus.py)
    │  asyncio.Queue per engagement      (bus.py)
    ▼
Pipeline Thread  (blocking, ThreadPoolExecutor)
    │  orchestrator.py → committees → agent_loop.py
    │  pub.sendMessage() calls throughout
    ▼
Filesystem artifacts  (artifacts/{run_id}/)
```

---

## Pipeline Execution Model

The pipeline runs on a **blocking background thread** managed by `runner.py`.
Committees execute sequentially: **Recon → Planning → [GATE] → Retrieval → Reporting**.

```
Pipeline thread:
  orchestrator.py
    └─ asks operator via ask_user (pre-pipeline, blocks thread on threading.Event)
    └─ committee/recon.py     → agent_loop.py  → pub.sendMessage(agent.*)
    └─ committee/planning.py  → agent_loop.py  → pub.sendMessage(agent.*)
    └─ approval_gate_handler()                 ← blocks thread on ctx.approval_event
    └─ committee/retrieval.py → agent_loop.py  → pub.sendMessage(agent.*)
    └─ committee/reporting.py → agent_loop.py  → pub.sendMessage(agent.*)

FastAPI event loop (async, separate thread):
  bus.py  ←  pub.ALL_TOPICS  ←  pipeline thread
  call_soon_threadsafe → asyncio.Queue → SSE endpoint → browser
```

---

## SSE Bridge (`bus.py`)

PyPubSub fires synchronously on the pipeline thread. `bus.py` bridges it to the async
event loop.

```python
_queues: dict[str, asyncio.Queue] = {}   # keyed by run_id
_loop: asyncio.AbstractEventLoop          # captured at server startup

def _bridge(topic=pub.AUTO_TOPIC, **kwargs):
    run_id = kwargs.get("run_id")
    q = _queues.get(run_id)
    if q:
        event = {"topic": topic.getName(), **kwargs}
        _loop.call_soon_threadsafe(q.put_nowait, event)

pub.subscribe(_bridge, pub.ALL_TOPICS)
```

The SSE endpoint (`routes/events.py`) opens a `Queue` for the engagement and drains it
as `data: {json}\n\n` chunks in a `StreamingResponse`.

---

## Operator Chat Injection

The operator can inject messages to a committee leader mid-run via:
```
POST /engagements/{run_id}/chat/{agent_id}
Body: { "message": "..." }
```

**How it reaches the agent:**
1. `runner.py` holds `EngagementContext.agent_queues: dict[str, queue.Queue]` (one per leader).
2. The POST route puts the message onto the leader's `queue.Queue`.
3. `agent_loop.py`'s `run_agent()` accepts `operator_queue: queue.Queue | None`.
4. Between every agent loop iteration, the queue is drained.
5. Each message is injected via `backend.inject_user_message(text)` — appends a `user`
   turn to `_messages` before the next model call.

**The `on_operator_reply` callback:**
- Fires when `stop_reason == "tool_use"` after an operator injection.
- Does NOT fire on `end_turn` (which is the JSON artifact output — would show raw JSON in chat).
- When fired, emits an `agent.operator_reply` SSE event with the agent's text.

**Orchestrator ask_user (pre-pipeline):**
- Different mechanism: `ctx.reply_event: threading.Event` + `ctx.pending_question/answer`.
- Pipeline thread blocks on `reply_event.wait(timeout=300)`.
- POST /chat writes `ctx.pending_answer` and sets `reply_event`.
- SSE events: `orchestrator.question` (on block) and `orchestrator.answer` (on unblock).

---

## Approval Gate

Between planning and retrieval, the pipeline thread is held at a configurable gate.

```python
# runner.py — gate handler passed into orchestrator
def approval_gate_handler() -> bool:
    ctx.awaiting_approval = True
    pub.sendMessage("engagement.awaiting_approval", run_id=ctx.run_id)
    ctx.approval_event.wait()          # blocks pipeline thread
    return ctx.approval_approved       # True = proceed, False = reject

# routes/plan_review.py — resolves the gate
def resolve_approval(approved: bool):
    ctx.approval_approved = approved
    ctx.approval_event.set()           # unblocks pipeline thread
```

`PlanReviewChat` in the frontend sends multi-turn questions to `routes/plan_review.py`.
The route loads `recon.md` + `plan.md` as context for the LLM.
"approve" / "reject" keywords are detected **deterministically** (simple string match),
not by LLM — this is intentional and must not be changed to an LLM-based detection.

---

## EngagementContext

All mutable state for one engagement. Lives in `runner.py`.

```python
@dataclass
class EngagementContext:
    run_id: str

    # Orchestrator pre-pipeline gate
    reply_event: threading.Event
    pending_question: str | None
    pending_answer: str | None

    # Plan review approval gate
    approval_event: threading.Event
    approval_approved: bool
    awaiting_approval: bool
    plan_review_history: list[dict]   # LLM conversation history for plan review

    # Committee leader queues (operator chat injection)
    agent_queues: dict[str, queue.Queue]   # keyed by agent_id
```

---

## Component Map

### Backend: `src/athena/server/`

| Module | Responsibility |
|---|---|
| `app.py` | FastAPI app factory, mounts all routers |
| `bus.py` | PyPubSub → asyncio.Queue SSE bridge |
| `runner.py` | `EngagementContext`, pipeline thread via `ThreadPoolExecutor` |
| `routes/engagements.py` | POST /engagements, GET /engagements/{id} |
| `routes/events.py` | GET /engagements/{id}/events (SSE) |
| `routes/chat.py` | POST /engagements/{id}/chat/{agent_id} |
| `routes/artifacts.py` | GET /engagements/{id}/artifacts |
| `routes/plan_review.py` | Plan review Q&A + approval gate release |
| `routes/report_chat.py` | Post-engagement debrief LLM chat |

### Backend: `src/athena/`

| Module | Responsibility |
|---|---|
| `agent_loop.py` | Core `run_agent()` loop — the only place agents run |
| `orchestrator.py` | Top-level pipeline: summons committees, owns ask_user, fires gate |
| `artifacts.py` | Pydantic schemas + markdown renderers for all four artifact types |
| `config.py` | `AthenaConfig`, `PlanReviewConfig` dataclasses |
| `committees/recon.py` | Recon committee: Foundation-Sec two-class architecture |
| `committees/planning.py` | Planning committee |
| `committees/retrieval.py` | Retrieval committee |
| `committees/reporting.py` | Reporting committee |

### Frontend: `src/ui/src/`

| File | Responsibility |
|---|---|
| `App.jsx` | Global state (`useReducer`), SSE connection + dispatch, routing |
| `api.js` | All fetch calls to FastAPI (single source of truth) |
| `index.css` | All styles (single file, no component library) |
| `components/CommitteeGraph.jsx` | React Flow graph of agents |
| `components/ArtifactTable.jsx` | Sorted artifact list |
| `components/OperatorChat.jsx` | Mid-run chat with any leader |
| `components/PlanReviewChat.jsx` | Plan approval gate Q&A panel |
| `components/ReportChat.jsx` | Post-engagement debrief |
| `pages/EngagementRequest.jsx` | Start page |
| `pages/Dashboard.jsx` | Main engagement view |
| `pages/OrchestratorDialog.jsx` | Briefing / MITRE playbook tabs |

---

## SSE Event Taxonomy

Topic strings are the contract between pipeline and frontend. See `TERMS.md` for the
full list. Visual behaviours driven by these events:

| Event | UI Behaviour |
|---|---|
| `committee.started` | Node transitions from dim to full committee colour |
| `agent.spawned` | New agent node appears in committee subgraph |
| `agent.spun_down` | Node darkens to indicate completion |
| `agent.finding` `signal_critical` | Node latches red; badge persists; node shifts toward leader |
| `agent.finding` `signal_warn` | Node latches yellow; badge increments; gradual shift toward leader |
| `agent.finding` `signal_info` | Brief yellow flash, returns to base colour |
| `engagement.awaiting_approval` | Blue pulsing approval banner in Dashboard |
| `orchestrator.question` | Speech bubble on chief orchestrator node; "Reply" link |

---

## Artifact Criticality (for Artifact Table sort)

Derived from Pydantic schemas at serve time:

- `ReportArtifact` → `risk_rating` field directly
- `ReconArtifact` → highest `observations[].classification` (critical > warn > info > noise)
- `PlanArtifact` → highest `actions[].priority` (critical > high > medium > low)
- `RetrievalArtifact` → no criticality field; sorts last by default (see `WORKSPACE_TODO.md`)

---

## Foundation-Sec Integration

Two-class model architecture in the recon committee:

| Class | Model | Role |
|---|---|---|
| Operators | Claude (Haiku / Sonnet) | Tool execution, data collection |
| Analyst | Foundation-Sec-8B (Modal/vLLM) | CTI reasoning over operator findings |
| Leader | Claude Sonnet | Synthesis, artifact emission |

Foundation-Sec **cannot call tools** — its security fine-tuning broke function calling.
It receives pre-gathered findings and outputs structured markdown (no JSON, no code blocks).
Claude handles all tool execution. Do not attempt to give Foundation-Sec tools.

Hosted on Modal with an A10G GPU. Config in `athena.yml` under `provider: ollama` for
the `threat_analyst` specialist.

---

## Key Config

`athena.yml` — main config read by `AthenaConfig`:

```yaml
model:
  default: claude-haiku-4-5
  provider: anthropic
  ollama_base_url: https://<workspace>--athena-foundation-sec-serve.modal.run

plan_review:
  model: claude-haiku-4-5

committees:
  recon:
    specialists:
      - config: ./agents/recon/threat_analyst.yml
        provider: ollama
        model: foundation-sec-8b
```
