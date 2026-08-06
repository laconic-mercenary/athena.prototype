# 01 — Execution Model (Orchestrator → Leader → Elements)

*Demo briefing. The point: three nested levels of agents — higher levels **plan**, lower levels **act** — all driven by one small agent loop, coordinated by the harness.*

## The three levels

| Level | Who | Produces | Scope |
|---|---|---|---|
| **Orchestrator** | 1 agent, once per engagement | the **EngagementPlan** (objectives, per-committee briefs, gates) | whole engagement |
| **Leader** | 1 per committee | **Steps** (batches of Tasks) → the committee's typed artifact | one committee |
| **Element / Specialist** | N per committee | one **tool call** + a short raw result | one task |

### Orchestrator — sets the Objectives
- Runs once at "briefing." Reads the operator's instructions + the ensemble's **capability doc**
  (`capability.md` → `briefing_required`).
- Emits an `EngagementPlan`: `operator_instructions`, a `CommitteeBrief` per committee
  (`objective[]`, `constraints[]`, `emphasis[]`), and `gates[]` (operator-approval after a committee).
- May pause to ask the operator a question mid-briefing (bounded retries), then re-brief.
- Executes nothing itself — its plan is the contract the committees run against.

### Leader — creates the Steps and Tasks
- One per committee (recon / planning / exploit / reporting), driven by `leader.yml` + its brief.
- Works as a **just-in-time loop**: calls `submit_step(step)` where a Step = a batch of **Tasks**
  (each Task targets an element with a brief), observes the labelled results, then decides the next
  Step. It does **not** pre-plan the whole committee.
- Leader tools: `submit_step`, `finish` (synthesise the typed artifact), `select_result` (compare
  mode), `ask_operator`, `reply_operator`, `refuse_start`, `read_artifact` (optional upstream).
- Ends by calling `finish()` → emits the committee's Pydantic artifact.

### Element / Specialist — executes one Task
- Elements are the workers. Each element has 1+ specialists (`<role>.yml` prompt + `task.md`).
- A specialist runs a tiny agent loop, makes **one skill (tool) call** by default (per-element
  budget can raise it), and returns the raw result verbatim — the leader interprets it.
- **Compare mode**: an element with multiple specialists runs them in parallel and the leader picks
  the best with `select_result` (planning uses 3 analysts on 3 model families).

## The agent loop (`run_agent`) — same for every level
1. `backend.complete()` → model returns text + tool calls + a `stop_reason`.
2. `tool_use` → dispatch each tool, feed results back, loop.
3. `end_turn` → done (validate / finish).
4. `max_tokens` → **hard error** (RuntimeError) — no silent truncation.
- Bounded by `max_iterations` (specialists 30, leaders 500).
- Backend-agnostic: the loop never sees a provider's message format (Anthropic vs OpenAI-compatible).

## Threads
- Each **engagement** runs on a worker thread (`ThreadPoolExecutor`); PyPubSub events fire
  synchronously on that thread.
- The **orchestrator** runs on its own thread; the **workflow** (committee sequencing) runs
  alongside and coordinates via events + `threading.Event`s.
- **Compare mode** fans specialists across a `ThreadPoolExecutor` — fault-tolerant: a specialist
  that throws is dropped, the leader selects among survivors; the element fails only if **all** fail.
- `bus.py` bridges pub events → a per-run `asyncio.Queue` (`call_soon_threadsafe`) → **SSE** to the UI.
- Operator interaction is synchronous from the agent's view: `ask_operator` blocks on a
  `queue.Queue` until the operator (or a timeout) answers.

## Key harness features (the one-liners)
- **Typed artifacts** — every committee output is a Pydantic schema, validated at `finish()`,
  re-prompted if malformed.
- **Just-in-time Steps** — leaders adapt to findings; no rigid pre-plan.
- **Compare / select** — model diversity + leader adjudication.
- **Operator gates** — `operator_approval` between committees (Accept / Redo) + in-loop gates
  (element / step / tool) the operator can arm live.
- **Tool-call authorization** — side-effecting skills (`touches_target`) surface to the operator
  before they run when the tool gate is armed.
- **Budgets** — per-specialist tool-call cap (default 1, per-element override), global step budget,
  per-committee `max_steps`, bounded retry/iterate counts.
- **Live SSE stream** — every tool call, model message, gate, and finding is published to the console.
