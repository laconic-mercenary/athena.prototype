# Athena — Vocabulary Reference

This file defines all established terminology for the Athena project. Read it before
writing code that touches user-facing strings, system prompts, SSE topics, or API
routes. Consistency with these terms is mandatory — do not invent synonyms.

---

## Roles

**Operator**
The human using Athena. May be a red team lead, a bounty hunter, or a business-side
stakeholder authorising an engagement. Not necessarily a hands-on pentester.
Think of this person as submitting work orders to a team they cannot directly supervise.

**Chief Orchestrator**
The top-level agent that receives the operator's instructions and coordinates the
four committees. All operator input flows through the chief orchestrator first.
It runs `ask_user` to clarify scope before any committee starts.

**Leader / Committee Leader**
The senior agent inside each committee. Receives work scope from the chief
orchestrator, summons and directs its specialists, synthesises findings,
and emits the committee's artifact at the end. One leader per committee.

**Specialist**
A focused agent within a committee. Executes a narrow task (port scan, SQL probe,
web crawl) and reports findings to the leader. Multiple specialists run per committee.

---

## Pipeline Structure

**Engagement**
A single end-to-end run of the Athena pipeline against a named target. Identified by
a `run_id` (UUID). All artifacts, events, and chat history are scoped to an engagement.

**Run ID (`run_id`)**
UUID that uniquely identifies one engagement. Used as a key in `EngagementContext`,
as the SSE stream path (`/engagements/{run_id}/events`), and as the artifact directory
name (`artifacts/{run_id}/`).

**Committee**
A swarm of agents (one leader + N specialists) assembled to achieve a specific phase
goal. The four committees run sequentially: Recon → Planning → Retrieval → Reporting.

**Recon Committee**
Gathers intelligence on the target using open and closed sources. Uses Foundation-Sec
as an analyst agent for CTI reasoning. Outputs `recon.md`.

**Planning Committee**
Converts recon findings into an attack plan. Outputs `plan.md`.

**Retrieval Committee**
Executes the plan against the live target — the closest approximation to a real hacker
in the field. Outputs `retrieval.md`.

**Reporting Committee**
Converts retrieval findings into a formal engagement report. Outputs `report.md`.

---

## Artifacts

**Artifact**
The structured output of a committee or agent action, written to disk as JSON or
markdown under `artifacts/{run_id}/`. The four pipeline artifacts are:
`recon.md`, `plan.md`, `retrieval.md`, `report.md`.

**Observation**
A classified finding recorded during recon, stored in `ReconArtifact.observations`.
Each observation carries a `classification`: `signal_critical`, `signal_warn`,
`signal_info`, `noise`, or `unknown`.

**PlannedAction** (current) / **AttackNode** (proposed — see ROADMAP.md)
A discrete step in the attack plan produced by the planning committee.

**RetrievedFinding**
A finding from the retrieval committee, referencing the `action_id` (or future
`node_id`) it was executing when discovered.

---

## Ensemble Vocabulary

**Ensemble**
A named, versioned bundle of agents, skills, and knowledge bases that Athena's harness
can instantiate and run as a complete pipeline. The unit of distribution in the
marketplace. Example: "Red Teaming ensemble", "PCI-DSS Assessment ensemble".

**Harness**
The orchestration infrastructure that spawns, connects, and supervises agents within
an ensemble. Athena itself is the harness. Do not use "harness" to mean "framework"
in user-facing copy; it specifically refers to Athena's internal machinery.

**Agent Elements**
The individual agents bundled inside an ensemble — leaders and specialists. Displayed
in the marketplace as the "Agent Elements" composition count on an ensemble card.
(Not "agents", not "Agents Package".)

**Skills Granules**
The discrete tool skills bundled inside an ensemble — nmap wrappers, HTTP probes,
database connectors, etc. Displayed as "Skills Granules" on an ensemble card.
(Not "tools", not "skills".)

**Knowledge Granules**
The curated knowledge packages bundled inside an ensemble — CVE feeds, compliance
frameworks, threat intelligence, domain reference data. Displayed as "Knowledge Granules"
on an ensemble card. (Not "knowledge bases", not "data".)

---

## Gates and Interaction

**Approval Gate**
A blocking checkpoint in the pipeline thread. The operator must explicitly approve or
reject before the pipeline proceeds to the next phase. Currently implemented between
planning and retrieval as the only gate. The `threading.Event` pattern is used.
The UI shows a pulsing blue banner when a gate is open.

**Plan Review**
The specific approval gate after planning completes. The operator can chat with an LLM
that has `recon.md` + `plan.md` in context, then types "approve" or "reject" to release
the gate. Handled by `routes/plan_review.py`.

**Operator Chat**
The mid-run message injection interface. The operator sends a message to a committee
leader's `queue.Queue`; `agent_loop.py` drains the queue between iterations and injects
the message as a user turn. The leader's reply fires an `agent.operator_reply` SSE event.

**Hold** (planned — Goal 1)
A per-committee pause at phase completion. Distinct from the approval gate: a hold
suspends a committee at its output boundary so the operator can review before the next
committee starts. Not yet implemented.

---

## Infrastructure

**EngagementContext**
The Python dataclass in `runner.py` that owns all mutable state for one engagement:
`run_id`, `reply_event`, `pending_question`, `pending_answer`, `agent_queues`,
`approval_event`, `awaiting_approval`. One instance per active engagement.

**SSE Bridge**
The `bus.py` mechanism that routes PyPubSub events from the pipeline thread into the
FastAPI async event loop. Uses `call_soon_threadsafe` to push events into a per-engagement
`asyncio.Queue`. The SSE endpoint (`routes/events.py`) drains the queue.

**PyPubSub**
The in-process event bus used throughout the pipeline. All pipeline instrumentation
fires `pub.sendMessage(topic, **kwargs)`. The SSE bridge subscribes to `pub.ALL_TOPICS`.

**Foundation-Sec**
The security-specialist open-source model (Foundation-Sec-8B-Reasoning, based on
Llama 3.1 8B) used as the recon committee's threat analyst. It performs pure CTI
reasoning over pre-gathered operator findings. It cannot call tools — tool execution
always uses Claude. Hosted on Modal with an A10G GPU.

**Sarif Industries**
The fictional company used as the red team target in the Docker Compose test environment.
Target hostname: `target`. Database: `pgdatabase` (PostgreSQL 16).

---

## SSE Event Topic Names

Use these exact strings — they are the contract between backend and frontend.

```
engagement.started
engagement.completed
engagement.rejected
engagement.awaiting_approval

committee.started
committee.completed
committee.artifact_emitted

agent.spawned
agent.spun_down
agent.tool_called
agent.finding
agent.operator_reply

orchestrator.question
orchestrator.answer
```

`agent.finding` classification values: `signal_critical` | `signal_warn` | `signal_info` | `noise` | `unknown`
