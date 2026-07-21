# Athena — Capability Roadmap

Three goals agreed before the red team demo. Read this before implementing anything
that touches gates, orchestrator dialogue, or committee architecture. These plans
represent decisions already made — build toward them, not against them.

---

## Goal 1 — True Human-Agent Intervention (Priority 1 / Demo-critical)

**Problem today:** The operator can inject messages to a leader mid-run, but the leader
finishes its current work regardless. The pipeline can only be blocked at the single
hardcoded gate between planning and retrieval. There is no way to hold a committee at
its completion boundary, and chat injections don't reliably cause the agent to change
course.

**Target behaviour:**
- Operator says "pivot to the database subnet" — the leader genuinely re-tasks its specialists.
- Operator can issue a **hold** at any phase boundary: "do not advance to planning until
  I release you" — pipeline blocks at that committee's completion.
- The approval gate mechanism is generalised — configurable at any phase transition,
  not hardcoded to planning→retrieval.

**Architecture approach:**
- Extend `EngagementContext` with `per_committee_hold: dict[str, threading.Event]`
  and `hold_active: dict[str, bool]`.
- Each committee checks for a hold at its completion boundary before returning to
  the orchestrator.
- New API endpoints: `POST /engagements/{id}/committees/{name}/hold` and `.../release`.
- UI: per-committee hold/release controls on each committee node in the Dashboard.
- The existing `operator_queue` injection is correct for mid-run direction — the gap is
  the system prompt. Update each leader's `yml` to explicitly instruct: "If an operator
  message says to stop or pivot, acknowledge it and end your current work loop."

**Do not:** add another hardcoded gate. Generalise the existing one.

---

## Goal 2a — Collaborative Engagement Planning (Priority 2 / Pre-demo achievable)

**Problem today:** The orchestrator's `ask_user` dialogue before the pipeline starts is
a simple one-shot clarification. The operator gets no visibility into what the pipeline
will do, cannot configure gates, and cannot give per-committee instructions.

**Target behaviour:**
The operator and orchestrator conduct a substantive multi-turn planning dialogue before
any committee starts. The orchestrator emits a structured **EngagementPlan** artifact
at the end. The pipeline reads this plan and wires itself accordingly.

**EngagementPlan would include:**
- Scope and named objectives per committee
- Which phase transitions have approval gates (operator-configurable)
- Per-committee custom instructions (e.g., "Reporting: output findings as MITRE ATT&CK Navigator layer")
- Priority targets, exclusions, engagement constraints (stealth level, rate limits)

**Architecture approach:**
- Add `EngagementPlan` Pydantic schema to `schemas.py` (or `artifacts.py`).
- Orchestrator's final briefing turn emits the plan as a structured artifact.
- `runner.py` reads the plan before the committee pipeline and configures:
  - Which `threading.Event` gates to install
  - Per-committee instructions injected into each leader's initial context at spawn time
- The `OrchestratorDialog` (briefing page) surfaces the plan for operator review before
  they click Proceed.

---

## Goal 2b — Dynamic Agent Spawning (Multi-session / Plan now, build after)

**Problem today:** Specialists within a committee run sequentially. The leader cannot
spawn multiple instances of the same specialist to work sub-tasks in parallel.

**Target behaviour:**
The recon leader decides mid-execution to spawn three port scanner agents assigned to
different subnets simultaneously. Results arrive asynchronously; the leader synthesises
when all complete.

**Architecture approach:**
- Leader gains a `spawn_specialist(task: str) → result` tool.
- Under the hood: a new `agent_loop` coroutine runs in the event loop, returns a typed
  artifact when complete.
- This is the fan-out / fan-in pattern: leader decomposes scope, spawns N specialists,
  collects results, synthesises.
- This is an architectural shift — today agents are sequential within a committee.
  Plan and sketch this for the red team demo whiteboard; build it after.

**Sequencing note:** Goal 2a is achievable as a prototype before the demo. Goal 2b is
multi-session work. Do not conflate them.

---

## Goal 3 — Ensemble Architecture — Beyond Red Teams (Strategic / Roadmap)

**Vision:** Athena becomes a general-purpose agentic orchestration platform. The orchestrator
is ensemble-aware — it discovers and executes any installed ensemble, not just the four
hardcoded red team committees.

**Ensemble definition:**
A named, versioned package containing:
- Agent definitions (YAML system prompts, tool assignments, model selection)
- Skills (tool implementations — Python callables)
- Knowledge (context files, reference data, threat feeds)
- A manifest (`manifest.yml`) declaring pipeline structure and capabilities

```
ensembles/
  red-teaming/
    manifest.yml       # name, version, description, pipeline topology
    agents/
      recon-leader.yml
      port-scanner.yml
      vuln-correlator.yml
    skills/
      nmap_scan.py
      http_probe.py
    knowledge/
      cve_feed.json
```

**Architecture approach:**
- Orchestrator gains ensemble discovery: reads `ensembles/*/manifest.yml` at startup.
- `manifest.yml` schema defines the pipeline topology (which agents, in which committees,
  with which tools and knowledge).
- Marketplace becomes a real package registry — published ensembles can be downloaded
  and installed into `ensembles/`.
- `runner.py` instantiates committees dynamically from the manifest rather than from
  hardcoded imports.

**This is a multi-quarter effort.** It is documented here so Goal 1 and Goal 2 implementations
do not make it structurally harder. When touching committee instantiation or the pipeline
topology, keep it compatible with future manifest-driven discovery.

---

## Intent Tree (Recon → Planning interface upgrade)

Separate from the three goals above, `projects/RECON_PLANNING.md` describes an upgrade
to the Planning output format: replacing `PlannedAction` flat lists with an **intent tree**
of `AttackNode` objects with `on_success`/`on_failure` edges and a `creativity: float`
parameter on `PlanArtifact`.

This is a schema change affecting `schemas.py`, `planning.py`, `retrieval.py`, and
`artifacts.py`. Read `RECON_PLANNING.md` in full before touching any of these files.

Key open questions from that doc (not yet resolved):
1. Tree walk owner: Python-deterministic vs. leader-driven LLM traversal.
2. Node ID assignment: before or after LLM generation.
3. Foundation-Sec command extraction: parse in `recon.py` or pass raw to planners.
4. `creativity` default: `0.5` proposed.
