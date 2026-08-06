# Athena — Vocabulary Reference

Defines all established terminology. Read this before writing code that touches
user-facing strings, system prompts, SSE topics, or API routes. Consistency with
these terms is mandatory — do not invent synonyms.

---

## Roles

**Operator**
The human using Athena. Reviews each committee's output at the gate, approves or redoes,
and may inject instructions to leaders mid-run. Not necessarily a technical practitioner —
the platform is designed so a non-hands-on stakeholder can supervise the engagement.

**Orchestrator**
The top-level agent that receives the operator's instructions and proposes an engagement
plan. Runs a multi-turn briefing dialogue before any committee starts; the operator
approves or revises the plan before the harness begins the workflow.

**Leader / Committee Leader**
The senior agent inside each committee. Drives the JIT planning loop — submits steps,
interprets element outputs, and emits the committee's structured artifact when done.
One leader per committee.

**Specialist**
A focused agent within an element. Calls the element's declared skills and returns
output to the leader. An element with multiple specialists runs in compare mode —
all variants run in parallel, and the leader selects the most credible result.

---

## Pipeline Structure

**Engagement**
A single end-to-end run through the ensemble's workflow graph. Identified by a `run_id`
(UUID). All artifacts, SSE events, and chat history are scoped to one engagement.

**Run ID (`run_id`)**
UUID that uniquely identifies one engagement. Used as the key in `EngagementContext`,
as the SSE stream path (`/engagements/{run_id}/events`), and as the artifact directory
(`artifacts/{run_id}/`).

**Committee**
One phase of the workflow. A leader runs the JIT loop, dispatching elements (in parallel)
across one or more steps, and emits a validated artifact at completion. Committee names
and sequencing are declared in the ensemble manifest.

**Element**
A named unit of work within a committee step. Elements in the same step run
concurrently. Each element has one or more specialists and a declared skill set.

**Step**
One iteration of the leader's JIT loop. A step contains one or more element tasks.
The leader decides which elements to run in each step.

---

## Artifacts

**Artifact**
The validated Pydantic output a committee emits when its leader calls `finish()`.
Stored to disk as JSON under `artifacts/{run_id}/{committee}.json`. Each artifact
is the primary input for downstream committees that declare it in `consumes.required`.

**`render_full()`**
A method on the artifact schema that returns a full-fidelity human-readable text
representation. Injected into downstream leaders' initial briefs and shown on the
artifact detail view.

**`render_digest()`**
A method on the artifact schema that returns a compact summary. Shown in the gate
dialog body so the operator can assess adequacy at a glance.

---

## Ensemble Vocabulary

**Ensemble**
A self-contained directory containing a manifest, leader prompts, specialist prompts,
skill implementations, and output schemas. Defines the entire workflow — committees,
elements, specialists, skills, and the workflow graph. Swapping the ensemble changes
what Athena does without touching the harness.

**Harness**
The orchestration infrastructure in `src/athena/` that loads and runs an ensemble.
Athena itself is the harness. Do not use "harness" to mean "framework" in user-facing
copy — it refers specifically to Athena's internal machinery.

**Manifest** (`manifest.yml`)
The YAML file at the ensemble root that declares the workflow graph, committee
configuration, element and specialist assignments, and the skills registry.

**Skill**
A deterministic Python function exposed to specialists as a tool. Defined by a
`skill.yml` (tool description for the LLM) and an `impl.py` (the implementation).
Skills are scoped per-element in the manifest; a specialist can only call skills
declared on its element.

---

## Gates and Interaction

**Gate (committee gate)**
The between-committee operator checkpoint. After a committee completes, the harness
blocks until the operator issues a decision via `POST /engagements/{id}/gate`.
Options: **Accept** (advance to the next committee) or **Redo** (discard output and
re-run with optional guidance).

**Loop Gate (in-loop gate)**
An intra-committee operator checkpoint that can fire at three points: after a step
completes (`step`), after an element outputs a result (`element`), or before a
domain-tool executes (`tool`). Armed per-committee by the operator. Each kind blocks
on its own `threading.Event` until the operator responds.

**Operator Chat**
The mid-run message injection interface. The operator sends a message to any committee
leader's `queue.Queue`; the agent loop drains the queue between iterations and injects
it as a user turn. The leader's next tool-use response fires an `agent.operator_reply`
SSE event.

**Collaborator Co-approval**
An optional gate feature. The operator nominates a `@alias` at the committee gate;
the harness emails the collaborator (via Resend) and blocks until they reply APPROVE
or DENY. The thread is visible live in the gate dialog.

---

## Infrastructure

**EngagementContext**
The Python dataclass in `runner.py` that owns all mutable state for one engagement.
See `ARCHITECTURE.md` for the full field listing.

**SSE Bridge**
The `bus.py` mechanism that routes PyPubSub events from the harness thread into the
FastAPI async event loop via `call_soon_threadsafe` and a per-engagement `asyncio.Queue`.

**PyPubSub**
The in-process event bus used throughout the harness and orchestrator. All harness
instrumentation fires `pub.sendMessage(topic, **kwargs)`. The SSE bridge subscribes
to `pub.ALL_TOPICS`.

---

## SSE Event Topic Names

Exact strings — the contract between harness and frontend. See `ARCHITECTURE.md` for
the full taxonomy with descriptions.

```
engagement.completed          engagement.rejected
engagement.aborted            engagement.approved
engagement.plan_revision      engagement.collaborator_pending

orchestrator.question         orchestrator.answer
orchestrator.message

committee.started             committee.completed
committee.ask_operator        committee.operator_replied
committee.result_selected

step.started                  step.completed
step.superseded               task.started
task.completed

agent.spawned                 agent.spun_down
agent.tool_called             agent.tool_result
agent.model_text              agent.operator_reply
agent.failed

gate.redo_unsupported

collaborator.operator_message collaborator.replied
```
