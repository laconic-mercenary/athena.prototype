# Ensembles — Architecture Design

This document captures the agreed design for the Athena ensemble system.
Reference it before implementing any part of the ensemble layer.
The example ensemble lives at `202607/_example/ensembles/red-teaming/1.0.0/`.

---

## Vocabulary (bottom → top)

**Skill**
A Python callable that interacts with the world — `nmap_scan`, `http_get`, `postgres_query`.
Has three layers: a name/description the LLM uses to decide when to call it, a parameter
schema it must conform to, and an implementation the harness executes. Skills do things;
knowledge knows things.

**Specialist**
An agent that uses skills. Defined by a YAML system prompt with a model assignment and
a list of skills it can call. Can have ensemble-level skills (granted via the manifest)
and agent-level skills (declared in the specialist's own yml, co-located with their impl).

**Element**
N specialists running the same task. Two modes:
- `combine` — each specialist covers a different domain; outputs assembled by the leader.
- `compare` — same specialist run N times at different temperatures; leader selects the best.

The element is a black box to the layer above — it always appears as if a single specialist
produced the output, regardless of how many ran internally.

**Team**
N elements covering different aspects of the same committee task. Outputs combined by the
committee leader. Teams are implicit — declared by how the leader groups elements, not as
an explicit manifest construct for now.

**Committee**
A node in the workflow graph. Has a leader, one or more elements, and typed input/output
contracts (Pydantic schemas). The leader decomposes the committee's brief into element
assignments, runs them, and assembles the final committee artifact.

**Workflow**
The directed graph of committees. Defines valid transitions between nodes including
back-edges (retry). Entry node, terminal nodes, and gate conditions are all declared
in the manifest.

**Orchestrator**
Controls workflow flow. Does not belong to any ensemble — it is harness-level.
Selects the ensemble, loads it, reads `capability.md`, produces an `EngagementPlan`
during the briefing dialogue, and navigates the graph at runtime using that plan.

---

## Ensemble Package Layout

```
ensembles/
  <name>/
    <version>/              # semver; harness defaults to latest
      manifest.yml          # harness reads: graph, schemas, skills, element wiring
      capability.md         # orchestrator reads: what each committee does, adequacy criteria
      schemas/              # Pydantic output contracts, one per committee
      committees/
        <name>/
          leader.yml        # manifesto: leader identity + output contract (system prompt)
          playbook.md       # operating doctrine: element inventory, sequencing, adaptation rules
          elements/
            <element-id>/
              task.md       # interface contract: assignment template, output shape, limitations
              <specialist>.yml
      skills/
        <skill-id>/
          skill.yml         # name, description, parameter schema (what the LLM sees)
          impl.py           # Python callable (co-located for ensemble-bundled skills)
      knowledge/            # (not yet implemented — future)
```

Skills can also live at the specialist level. If a specialist has domain-specific tools
(proprietary API clients, custom file format parsers), they are declared inline in the
specialist yml and their impl is co-located with the agent definition.

---

## Compare Mode (Elements)

When `mode: compare`, the harness runs the same specialist N times at configured
temperatures and returns all outputs to the committee leader for selection.

```yaml
# in manifest.yml
- id: network_plan
  mode: compare
  judge: leader           # leader selects/synthesises best output
  instances: 3
  temperatures: [0.3, 0.7, 1.0]
  execution: reasoning_only   # harness enforces: no skills with side effects
  specialists:
    - committees/planning/elements/network_plan/planner.yml
  skills: []
```

**Judge types:**
- `leader` — committee leader receives all N labeled candidates and selects/synthesises.
  Preferred: leader already holds full engagement context (brief + prior artifacts).
  **Implemented.**
- `scorer` — deterministic Python function scores outputs against `task.md` criteria.
  **Raises NotImplementedError — not yet implemented.**
- `agent` — dedicated judge agent receives all N outputs and task.md, returns best.
  **Raises NotImplementedError — not yet implemented.**

**Important:** `compare` mode must only be applied to `reasoning_only` elements.
Elements that make real network or database calls cannot be multiplied — this would
generate N× the traffic and is a SIEM trigger risk.

Safe for compare: planning specialists, reporting specialists, threat analysis.
Unsafe for compare: network_scan, service_probe, web_crawl, web_retrieval, db_retrieval.

The leader must be explicitly instructed (in its system prompt) that when candidates
are provided, its job is selection or synthesis — not generating a third option from scratch.

---

## Orchestrator Design

The orchestrator is a harness-level agent — it does not belong to any ensemble.
Its system prompt is ensemble-agnostic. Ensemble-specific knowledge (`capability.md`)
is injected into the conversation at session start, not baked into the system prompt.

### System prompt (ensemble-agnostic)

```yaml
title: Chief Orchestrator
model: claude-sonnet-4-6
system: |
  You are the Chief Orchestrator. You are harness-level — you do not belong to any
  ensemble. You operate in two phases across the same conversation.

  == Phase 1: Briefing ==
  The loaded ensemble's capability document is provided in your first message.
  Read it fully before responding to the operator.

  Conduct a dialogue to clarify the engagement objective, scope, and any constraints.
  Ask only what you need — the operator is a practitioner, not a client.
  When ready, produce an EngagementPlan JSON as your final briefing message.
  The operator's Proceed gesture is approval.

  == Phase 2: Gate decisions ==
  After each committee completes, the harness injects the committee artifact and
  invokes you with one of four tools. Use exactly one per gate.

    advance()               — output meets adequacy criteria; proceed to next committee
                              (or close the engagement if this is the terminal committee)
    retry(note: str)        — output failed adequacy criteria; re-run fresh; note appended
                              to the committee's objective list
    iterate(note: str)      — output is adequate but improvable; re-run with prior artifact
                              shown; note appended to the committee's objective list
    ask_operator(question)  — escalate to operator before deciding; pipeline pauses

  Evaluate against the adequacy criteria in the capability document (already in your
  context). Reference your EngagementPlan to recall what you expected from this committee.
  Do not advance if adequacy criteria are not met. Do not retry more than three times
  on the same committee without asking the operator.

  == EngagementPlan schema ==
  <placeholder — to be filled when EngagementPlan is formalised as typed schema>
```

### Context 1 — Briefing (session start)

Harness injects into the first user turn:

```
== Ensemble: <name> v<version> ==

<full capability.md content>

== Operator ==
<operator's first message>
```

### Context 2 — Gate callback (continuation of same conversation)

The orchestrator conversation stays open across the pipeline. When a gate fires,
the harness appends to the existing conversation:

```
== Gate: <gate_type> — <committee> complete ==

== Committee output ==
<committee artifact, structured>

Evaluate against adequacy criteria for the <committee> committee.
Use advance(), retry(note), or ask_operator(question).
```

The orchestrator already has `capability.md` and the EngagementPlan in context from
the briefing. Only the new artifact and gate prompt need to be injected.
Prior gate decisions and artifacts remain visible — the orchestrator sees the full
engagement trajectory.

### Gate tools

Provided by the harness at gate callback time only — not available during briefing.

| Tool | Signature | Effect |
|------|-----------|--------|
| `advance` | `advance()` | Proceed to next committee; close engagement if terminal |
| `retry` | `retry(note: str)` | Failure retry — re-run fresh; note appended to objective list |
| `iterate` | `iterate(note: str)` | Iteration retry — re-run with prior artifact shown; note appended to objective list |
| `ask_operator` | `ask_operator(question: str)` | Pause pipeline; surface question via operator chat |

The harness switches tool availability between phases: no gate tools during briefing,
gate tools injected at each callback. This prevents the orchestrator from calling
`advance()` before any committee has run.

`ask_operator` also handles unscheduled escalation (capability.md "Ask the operator if:"
conditions) — it is just one of the four gate tools, not a separate mechanism.

---

## Engagement Plan

The orchestrator produces an `EngagementPlan` at the end of the briefing dialogue.
The operator reviews and approves it (the existing Proceed button is the approval gesture).
The harness validates the plan before the pipeline starts and uses it to:
- Wire `operator_approval` gates at the declared phase transitions
- Build the per-committee brief passed to each leader at spawn time

**Key property:** the orchestrator evaluates at every committee boundary (always implicit).
`operator_approval` gates are the only gate type declared in the plan — they are the
boundaries where human action is required before the pipeline continues.

### Typed schema (`src/athena/engagement_plan.py`)

```python
class GateType(str, Enum):
    operator_approval = "operator_approval"
    # extensible: external_approval, timed_review, etc.

class Gate(BaseModel):
    after: str      # committee name — validated against manifest at runtime
    type:  GateType

class CommitteeBrief(BaseModel):
    objective:   list[str]   # ordered; most recent has highest weight; earlier items are context
    constraints: list[str] = []
    emphasis:    list[str] = []

class EngagementPlan(BaseModel):
    engagement_id:         str   # harness-assigned UUID; injected into orchestrator context
    operator_instructions: str
    committees:            dict[str, CommitteeBrief]
    gates:                 list[Gate] = []
```

`committees` keys are validated against the manifest's committee names at runtime.
`gates` is a list (not a dict) to allow multiple gate types per committee in future
and to preserve declaration order. Query: `[g for g in plan.gates if g.after == "planning"]`.

### Example (red-teaming ensemble)

```json
{
  "engagement_id": "<harness-assigned UUID>",
  "operator_instructions": "Assess the internal web app at 10.0.1.5 for credential exposure. Avoid aggressive scanning.",
  "committees": {
    "recon": {
      "objective": "Map open ports and web paths on 10.0.1.5; flag any version disclosure.",
      "constraints": ["timing T2 or slower", "avoid /admin brute-force"],
      "emphasis": ["web application paths", "TLS configuration"]
    },
    "planning": {
      "objective": "Prioritise actions targeting credential exposure and web misconfigurations.",
      "constraints": [],
      "emphasis": ["signal_critical observations from recon"]
    },
    "retrieval": {
      "objective": "Execute approved actions; retrieve credentials or sensitive files if accessible.",
      "constraints": ["read-only database access"],
      "emphasis": []
    },
    "reporting": {
      "objective": "Produce a formal report suitable for the client's security team.",
      "constraints": [],
      "emphasis": []
    }
  },
  "gates": [
    {"after": "planning", "type": "operator_approval"}
  ]
}
```

### Harness-built committee brief

When spawning a committee leader, the harness builds its initial message as:

```
== Engagement brief ==
Objective: <objective>
Constraints: <constraints>
Emphasis: <emphasis>

== Prior committee outputs ==
<upstream artifacts>

== Your playbook ==
<playbook.md content>

== Element task cards ==
<task.md for each element>

Begin with your CommitteePlan.
```

The orchestrator's per-committee brief (objective/constraints/emphasis) is the engagement-specific
layer. The playbook and task cards are the ensemble-static layer. Both are injected together.

---

## Capability Document (`capability.md`)

Read by the orchestrator at ensemble load time. Written by the ensemble author.
The orchestrator never reads `task.md` or `playbook.md` (those are committee-internal).

Must contain:
- What the ensemble does and what it produces
- Per-committee description: inputs, outputs, what "adequate" looks like
- When to advance vs. retry vs. ask the operator
- Model notes (e.g. Foundation-Sec cannot call tools)
- Engagement constraints (allowlists, read-only enforcement)

---

## Committee Document Schema (three layers)

Each committee has three documents. Each has a distinct audience and scope.

### `leader.yml` — Manifesto

The leader's **identity and output contract**. Lives in the system prompt — always in
context, so keep it short (~400–600 tokens).

Contains: who the leader is, what the committee produces, the output format (Phase 1
plan JSON, Phase 2 artifact), harness-interface tools (`record_observation`, etc.),
classification guides, operator interrupt handling.

Does NOT contain: element inventory, operating procedure, domain knowledge.

### `playbook.md` — Operating Doctrine

The committee's **standard operating procedure**. Injected into the leader's initial
message alongside element task cards. Written by the ensemble author per committee.

Contains: element inventory table (one line per element, pointer to task.md), standard
sequencing pattern, decision criteria for when to adapt (passive-only engagement, web-only
target, large CIDR range, etc.), what the leader does not do.

The playbook gives the leader enough doctrine to avoid reinventing sequencing from
scratch each run, while leaving element briefs short enough for specialist creativity
to operate within them.

### `task.md` — Element Interface Contract

One per element. Read by the committee leader (injected into initial message). Not read
by the orchestrator.

**Standard format:**

```
# Element: <id>

<One sentence: what this element does.>

## Assignment template
<brief text with [VARIABLES] the leader fills in from the engagement brief>

## Output shape
<fields, format, level of detail>

## Skills
<list with one-line description of each skill available>

## Limitations
<what this element cannot or should not be asked to do>

## Adequacy criterion
<what "good enough" looks like — used by the leader when reviewing output;
 in compare mode with judge: leader, this is the explicit evaluation criterion>
```

Serves two purposes:
1. Leader reads it before planning to know what brief to write for each element.
2. In `compare` mode with `judge: leader`, the adequacy criterion is the reference
   the leader uses when selecting among N candidate outputs.

**Model capability targets:**

| Layer | Model | Reason |
|-------|-------|--------|
| Committee leader | claude-sonnet-4-6 | Reads 3+ docs + artifacts, produces plan, judges compare candidates, writes final artifact |
| Reasoning specialist (compare mode) | claude-haiku-4-5 or smaller | Narrow focused task; running 3× means cost matters |
| Tool-using specialist | claude-sonnet-4-6 or claude-haiku-4-5 | Needs reliable function calling |
| Foundation-Sec | foundation-sec-8b via Ollama | Domain-tuned; cannot call tools |

---

## CommitteePlan

The structured work plan the committee leader emits in **Phase 1** before the harness
executes anything. The harness validates it (Pydantic) before running a single element.
If invalid, the harness injects the validation error back to the leader for revision.

**Schema** (`src/athena/committees/plan.py` — harness-level, not ensemble-specific):

```python
class CommitteeTask(BaseModel):
    element: str   # must match an element id declared for this committee in the manifest
    brief:   str   # leader-written assignment; fills [VARIABLES] from the element's task.md

class CommitteeStep(BaseModel):
    id:          str
    description: str
    tasks:       list[CommitteeTask]   # parallel; minimum 1

class CommitteeGoal(BaseModel):
    id:          str
    description: str
    steps:       list[CommitteeStep]   # sequential in list order; minimum 1

class CommitteePlan(BaseModel):
    rationale: str                     # 1-2 sentences: why this structure for this engagement
    goals:     list[CommitteeGoal]     # sequential in list order; minimum 1
```

**Execution model:**
- Goals execute in list order (sequential)
- Steps within a goal execute in list order (sequential)
- Tasks within a step execute in parallel
- No `depends_on` fields — list order is the dependency

**Two-phase leader conversation:**

Phase 1 — leader reads playbook + task cards + engagement brief → emits CommitteePlan JSON.
No element calls. Harness validates and executes the plan.

Phase 2 — harness injects all element results structured by goal/step → leader synthesises
the final committee artifact.

Results are returned to the leader in plan order:

```
== Goal 1: <description> ==

  Step <id>: <description>
    [element_id]
    <output>

    [element_id]
    <output>

  Step <id>: <description>
    [element_id]
    <output>

== Goal 2: <description> ==
  ...

All elements complete. Proceed to synthesis.
```

**Why two phases:** prevents the reactive tool-calling failure mode where the leader
starts summoning elements greedily before forming a complete plan. The leader has no
summon tool available in Phase 1 — it can only emit the plan JSON. The affordance
enforces the separation structurally, not just via prompt instruction.

---

## Task Document (`task.md`)

See **Committee Document Schema → task.md** above for the full format specification
and the assignment template standard.

In `compare` mode, the adequacy criterion section doubles as the judge criterion —
the leader uses it explicitly when selecting among N candidate outputs.

---

## Retry Mechanics

Two semantically distinct retry types with different harness behaviour.

### `retry(note: str)` — Failure retry

Output did not meet adequacy criteria. Something went wrong.

- Prior artifact **not shown** to the committee leader on re-spawn — fresh start,
  avoid anchoring on bad output.
- `objective` list in `CommitteeBrief` gets the note appended as a new entry.
  The harness appends; the orchestrator writes the refinement, not a full restatement.
- Committee leader is told: *"Your previous output did not meet adequacy criteria. Begin fresh."*
- **Limit: 3 failure retries per committee.** The harness injects the current count
  into the gate callback prompt (`attempt N of 3`) — the orchestrator sees it and can
  decide to ask the operator rather than consuming the last retry blindly. The limit
  is informational, not mechanically enforced; the orchestrator can override by calling
  `ask_operator` instead.

### `iterate(note: str)` — Iteration retry

Output was adequate, but the orchestrator wants improvement on a specific aspect.

- Prior artifact **is shown** to the committee leader — it is the starting point.
- `objective` list in `CommitteeBrief` gets the note appended as a new entry,
  same as failure retry.
- Committee leader is told: *"Your output is acceptable. Refine the following aspect."*
- **Limit: 150 iteration retries per committee.** Intentionally high — this enables
  autonomous refinement loops where the orchestrator iterates until satisfied.
  Count is injected into the gate callback for transparency.

### `CommitteeBrief` objective as a list

```python
class CommitteeBrief(BaseModel):
    objective:   list[str]   # ordered; most recent has highest weight; earlier items are context
    constraints: list[str] = []
    emphasis:    list[str] = []
```

On first spawn: `objective = ["<original objective from briefing>"]`  
After retry/iterate: the harness appends the note as a new entry.  
The LLM treats later entries as more authoritative — earlier entries provide context
for how the objective evolved, not competing instructions to satisfy equally.

### Harness-built brief on retry/iterate

```
== Engagement brief ==
Objective:
  1. <original objective>
  2. <retry or iteration note>    ← most recent; highest weight
Constraints: ...
Emphasis: ...

[== Previous output ==           ← iterate only; absent on retry
<prior committee artifact>]

== Prior committee outputs ==
<upstream artifacts from earlier committees>

== Your playbook ==
...

== Element task cards ==
...

This is a [retry / refinement]. Begin with a revised CommitteePlan.
```

---

## Output Contracts

Pydantic schemas in `schemas/`. One per committee, declared in the manifest.
The harness validates committee output against its schema before passing it downstream.
Type errors surface at the committee boundary, not inside the next committee's processing.

On retry (back-edge): the committee's artifact is **overwritten** by the new run.

---

## Versioning

Each ensemble is versioned with semver under its name directory.
The harness defaults to `latest` (highest semver present) when no version is specified.
The orchestrator's ensemble registry (future) will manage version discovery.
For now: `latest` = the only version present in the `ensembles/` directory.

---

## Open Design Gaps — Orchestrator Layer

**1. Orchestrator manifesto and context design** _(Resolved)_
See **Orchestrator Design** section above.

**2. EngagementPlan has no typed schema** _(Resolved)_
See **Engagement Plan → Typed schema** above. Location: `src/athena/engagement_plan.py`.
`orchestrator_review` removed as a gate type — orchestrator evaluates at every boundary
implicitly; only `operator_approval` needs to be declared in the plan.

**3. Gate callback — what the orchestrator receives** _(Resolved)_
See **Orchestrator Design → Context 2** above. Conversation continuity means
`capability.md` and the EngagementPlan are already in context; the harness injects
only the new artifact and gate prompt.

**4. Retry brief mechanics** _(Resolved)_
See **Retry Mechanics** section above.

**5. Unscheduled operator escalation from a gate** _(Resolved)_
`ask_operator(question)` is one of the four gate tools. No separate mechanism needed.
See **Orchestrator Design → Gate tools** above.

**6. EngagementPlan submission mechanism** _(Resolved)_

The orchestrator submits the plan via a `submit_plan` tool available during briefing only
(not at gate time). The harness tool dispatch validates immediately against the Pydantic
schema and returns either a validation error (orchestrator revises and resubmits in the
same conversation) or `"Plan accepted. Awaiting operator Proceed."` The Proceed button
activates on a clean `pub.sendMessage("engagement.plan_ready")` triggered by the tool
dispatch — not by text scanning at click time.

This replaces the current fragile pattern in `orchestrator.py` where the harness calls
`extract_json` on the orchestrator's final message and recovers from prose with
`_MAX_BRIEFING_ATTEMPTS` restarts. The `submit_plan` tool gives the orchestrator
immediate structured feedback and keeps the entire briefing in one continuous conversation.

**7. Operator rejection at `operator_approval` gate** _(Resolved — no change)_

Rejection means the engagement starts over. The existing `resolve_approval(approved=False)`
path in `runner.py` already returns `None` from `run_orchestrator` and fires
`engagement.rejected`. No new mechanism needed.

**8. Terminal committee gate behavior** _(Resolved)_

The manifest encodes terminality via `transitions: []`. The harness checks transitions
after every `advance()` call:
- `transitions` non-empty → look up next node, spawn next committee
- `transitions: []` → close the engagement

`advance()` at the terminal node means "done" rather than "proceed." No new tools or
special cases — the orchestrator calls the same four gate tools at every boundary.
The harness determines the outcome of `advance()` from the graph position.
The orchestrator may still call `iterate(note)` or `ask_operator` at the terminal
boundary before choosing to advance.

---

## Not Yet Designed — Ensemble Layer

- **Knowledge granules** — declaration format, injection mechanism, candidates for this ensemble.
- **Ensemble registry / database** — how the orchestrator discovers and selects ensembles.
- **Parallel element execution** — elements within a team currently run sequentially.
  True fan-out/fan-in (Goal 2b) is a prerequisite for realising the full team model.
- **Ensemble distribution** — how ensembles are packaged, published, and installed from the marketplace.
