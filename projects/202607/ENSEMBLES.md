# Ensembles — Architecture Design

This document captures the agreed design for the Athena ensemble system **and is now an
implementation handoff.** Companion docs: `ENSEMBLE_UI.md` (UI rework), and two example ensembles
under `202607/`: `_inventory/` (a tiny validated reference) and `_example/…/red-teaming/…` (the demo).

---

## Start Here — For the Implementer

The ensemble **harness does not exist yet.** `src/athena/` is the *previous* ("workspaces") system
that hardcodes committees in Python. Your job is to build the **manifest-driven ensemble harness**
described here, reusing what's reusable from `src/athena/`.

**Reading order:** (1) this section + Implementation Plan below; (2) Vocabulary; (3) Committee
Execution — Iterative Re-Planning [the core loop], Orchestrator Design, Engagement Plan; (4) Operator
Interaction, Retry Mechanics, Output Contracts, Knowledge Granules; (5) Design Risks — **every `R#`
is RESOLVED/ACCEPTED/DEFERRED and encodes a binding decision, read them all**; (6) `ENSEMBLE_UI.md`.

**Two example ensembles (your build targets):**
- **`202607/_inventory/…`** — a tiny, benign, **validated** reference (count files by extension).
  Build the harness against this **first**: no consensus, no gates, read-only — the simplest possible
  end-to-end.
- **`202607/_example/…/red-teaming/…`** — the demo ensemble. **Still in the OLD format** (`mode:`, a
  two-phase recon `leader.yml`, three-layer docs only on recon). Migrating it to the settled model is
  a task (see Plan). It exercises consensus (planning), gates, and live findings.

**Reuse from `src/athena/` (don't rebuild):** `model_backend.py` (ModelBackend + Anthropic/Ollama/
Fake), `agent_loop.py` primitives, the server/SSE layer (`server/`, `bus.py`, the event bridge), and
`tools.py` (its functions are referenced as skills). **Replace:** the hardcoded `committees/*.py` with
manifest-driven loading + the iterative leader loop.

**Binding principles (do not drift):** LLM proposes / Python disposes; the LLM only ever *points*
(candidate ids, manifest-declared transitions) while Python validates and holds the bytes; every loop
is hard-bounded (step 12 / iterate 30 / global 200 Steps); every gate call logs a rationale.

---

## Implementation Plan (build order)

Build against `_inventory` first, then extend to `_example`. Phases are ordered by dependency.

**Phase 0 — Types + ensemble loader.**
- Harness Pydantic types in `src/athena/`: `EngagementPlan`, `CommitteeBrief`, `Gate`,
  `CommitteeStep`, `CommitteeTask` (schemas inline in this doc). There is **no `CommitteePlan`** — the
  leader streams Steps just-in-time.
- Ensemble loader: parse `manifest.yml` (workflow graph, committees, elements, skills registry), load
  `capability.md`, import the `schemas/` classes, load committee docs (`leader.yml`, `playbook.md`,
  `elements/*/task.md`, specialist ymls), resolve skills (`skill.yml` + `impl`). Validate that every
  referenced element id / schema name / skill id resolves.
- **Acceptance:** load `_inventory` and `_example` cleanly; clear error on a broken manifest.

**Phase 1 — Committee execution (the core).**
- Just-in-time leader loop: build the committee brief (objective + constraints + emphasis + playbook +
  task cards + upstream digest); `submit_step` / `finish` / `refuse_start`; execute each Step's Tasks
  **sequentially** (fan-out deferred); append Step outputs (tagged with a UUID `id`) to leader context;
  enforce `max_steps`; supersession; synthesise + schema-validate the artifact at `finish`; produce the
  **digest** (leader summary + per-committee adequacy fields).
- Element execution: **single-instance path** (run specialist with granted skills via skill dispatch).
- Skill dispatch: call the registry `impl` with validated params.
- Events: `step.*`, `task.*`, `agent.*` (incl. **incremental** `agent.finding` at synthesis, R9).
- **Acceptance:** run `_inventory`'s `scan` committee against a real directory → valid `ScanOutput` + digest.

**Phase 2 — Orchestrator + workflow driver.**
- Orchestrator (harness-level, ensemble-agnostic): briefing (inject `capability.md`; `ask_user`;
  `submit_plan` → validated `EngagementPlan`; `engagement.plan_ready` → operator Proceed).
- Workflow driver: traverse the graph; at each boundary invoke the orchestrator with the committee
  **digest** + gate tools (`advance(next_objective)` / `retry` / `iterate` / `ask_operator`), **log a
  rationale for every call**; refine the next objective on advance; honor `operator_approval` gates;
  enforce iterate (30) + global (200) budgets; `incomplete:true` cannot `advance` (R6b); `read_artifact`.
- **Acceptance:** run `_inventory` end-to-end (scan → report) driven by the orchestrator → `ReportOutput`.

**Phase 3 — Consensus + operator interaction.**
- Consensus (`instances>1`): run N at configured temperatures; **leader-id-selection judge** (structured
  `{chosen_candidate_id, reason}`, harness-validated, resolved to verbatim text). `scorer`/`agent` judges
  → NotImplementedError.
- Operator interaction: message typing (chat/flow/steering), `reply_operator`, committee `ask_operator`,
  `halt` (force-finish, operator-only), step-hijack at Task boundaries.
- **Acceptance:** run `_example` planning with consensus; operator can chat/halt.

**Cross-cutting deliverable — event taxonomy (OPEN).** Phases 1–3 must **define and document** the
SSE event topics they emit — `step.*`, `task.*`, `element.candidate`/`element.selected`,
`gate.decision` (+ rationale), `committee.digest`, `committee.ask_operator`, `engagement.halted`, and
the **incremental** `agent.finding` at synthesis. These names are only *indicative* today (see
`ENSEMBLE_UI.md` §0 and its Open Issue #1); **the harness is the authority.** Phase 4 / the UI consumes
them, so treat the finalized taxonomy as a hard deliverable of P1–P3, not an afterthought.

**Phase 4 — UI rework.** Per `ENSEMBLE_UI.md`, once the event taxonomy from Phases 1–3 is fixed.

**Migrate `_example` to the settled model** (do as you need it for Phases 1–3): manifest `mode:` →
drop / `instances:` + `teams:`; recon `leader.yml` → the just-in-time loop; add `playbook.md` +
three-layer `task.md` to planning/retrieval/reporting; add `max_steps`.

**Deferred — do NOT build now** (all marked in the doc): knowledge granules; ensemble registry +
distribution + the R7/R8 trust model; task fan-out (Tasks stay sequential); `scorer`/`agent` judges;
recursive/autonomous Teams (flat for the demo); OS-detection team selection (Linux hardcoded).

---

## Vocabulary (bottom → top)

**Skill**
A Python callable that interacts with the world — `nmap_scan`, `http_get`, `postgres_query`.
Has three layers: a name/description the LLM uses to decide when to call it, a parameter
schema it must conform to, and an implementation the harness executes. Skills do things;
knowledge knows things.

**Knowledge**
Read-only reference material a specialist consults — CVE tables, ATT&CK mappings,
threat-intel corpora. Modeled as a **read-only retrieval skill**: the specialist sees a
lookup callable, only the retrieved result enters context (not the whole corpus), and every
retrieval is logged. The backing store (flat file, structured index, or embeddings) is an
implementation detail behind that skill. Full design in **Knowledge Granules** below.

**Specialist**
An agent that uses skills. Defined by a YAML system prompt with a model assignment and
a list of skills it can call. Can have ensemble-level skills (granted via the manifest)
and agent-level skills (declared in the specialist's own yml, co-located with their impl).

**Element** — *depth*
The best answer to a **single** task: N specialists running the **same** task, varied by
temperature, with the committee leader selecting or synthesising the best result. `instances: 1`
(the default) is a plain single run; reasoning committees like Planning run N=3 for an optimal
output. The element is a black box to the layer above — it always appears as if one specialist
produced the output. `instances > 1` (temperature multiplication) is only permitted on
`reasoning_only` elements — see **Element Consensus** below; tool-using elements run `instances: 1`.

**Team** — *breadth; ideally a sub-committee*
Coverage of a domain: a group of elements doing different tasks (a *Network Team* =
{ssh, tcp, http, tls} probing elements). Breadth comes from Teams (different elements), depth
from Elements (temperature).
- **Ideal model:** a Team is an autonomous **sub-committee** — it has its own **Team Leader**
  that, given a high-level brief (e.g. just an IP), forms and sequences the element grouping it
  judges necessary and returns an aggregated result. This makes **Committee and Team the same
  recursive primitive** — a leader + a re-planning loop over children (sub-units or leaf
  elements), nested to any depth. The team leader composes from the ensemble's *fixed* element
  catalog (constrained composition, not arbitrary spawning).
- **Demo model:** kept flat — committees hold leaf elements directly, the committee leader
  sequences and aggregates, no team leaders. Recursion is deferred to real-world use.

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
      schemas/              # Pydantic output contracts, one per committee.
                            # Must include __init__.py that re-exports every schema class.
                            # Referenced in manifest.yml as `schemas.<ClassName>`
                            # (e.g. `output_schema: schemas.ScanOutput`). The harness
                            # imports the `schemas` package from the ensemble root and
                            # resolves the class by name.
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
      knowledge/
        <knowledge-id>/
          knowledge.yml     # name, description (access instruction), store type, corpus path
          <corpus files>    # flat file, SQLite index, or prebuilt embeddings
```

Skills can also live at the specialist level. If a specialist has domain-specific tools
(proprietary API clients, custom file format parsers), they are declared inline in the
specialist yml and their impl is co-located with the agent definition.

---

## Element Consensus (Temperature)

An element runs its specialist(s) at N temperatures; the committee leader selects or synthesises
the best result. `instances: 1` (the default) is a plain single run — the common case.
`instances > 1` is the consensus case. There is no `mode` field: consensus is simply what an
element *is*, and domain breadth lives one level up in **Teams**.

```yaml
# in manifest.yml — an element
- id: network_plan
  instances: 3
  temperatures: [0.3, 0.7, 1.0]
  execution: reasoning_only   # required when instances > 1; harness enforces no side-effect skills
  judge: leader
  specialists:
    - committees/planning/elements/network_plan/planner.yml
  skills: []
```

**Judge types (how the best of N is chosen):**
- `leader` — committee leader receives all N labeled candidates and selects/synthesises.
  Preferred: leader already holds full engagement context (brief + prior artifacts). **Implemented.**
- `scorer` — deterministic Python scores outputs against `task.md` criteria. **NotImplementedError.**
- `agent` — dedicated judge agent receives all N outputs and task.md, returns best. **NotImplementedError.**

**SIEM safety:** `instances > 1` multiplies execution, so it is only permitted on `reasoning_only`
elements. Multiplying a tool-using element would multiply real network/DB traffic — a SIEM
trigger. The harness rejects `instances > 1` on any element granted a side-effecting skill (**R7**).

- Consensus-safe (`instances > 1` OK): planning, reporting, threat_analysis.
- Single-instance only (`instances: 1`): network_scan, service_probe, web_crawl, web_retrieval, db_retrieval.

The leader must be instructed that when N candidates are provided its job is selection or
synthesis — not generating a fresh option from scratch.

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
  If the capability document contains a `briefing_required` section, work through each
  listed field with the operator and confirm it before calling submit_plan. This section
  is optional — not all ensembles declare one.
  When ready, call submit_plan with the EngagementPlan JSON. The harness validates the schema
  immediately and returns either a validation error (revise and resubmit in the same
  conversation) or "Plan accepted." The operator's Proceed gesture is final approval.

  == Phase 1 tools ==
  submit_plan(plan: JSON)   — submit the EngagementPlan; harness validates immediately;
                              available during briefing only
  ask_user(question: str)   — ask the operator a clarifying question during briefing

  == Phase 2: Gate decisions ==
  After each committee completes, the harness injects the committee digest and invokes you.
  Use exactly one gate tool per gate. You may call read_artifact first if the digest is not
  enough to decide.

    advance()                — output meets adequacy criteria; proceed to next committee
                               (or close the engagement if this is the terminal committee)
    retry(note: str)         — output failed adequacy criteria; re-run fresh; note appended
                               to the committee's objective list
    iterate(note: str)       — output is adequate but improvable; re-run with prior artifact
                               shown; note appended to the committee's objective list
    ask_operator(question)   — escalate to operator before deciding; pipeline pauses
    read_artifact(name: str) — pull a full on-disk artifact when the digest is not enough;
                               read-only, not a gate decision

  Evaluate against the adequacy criteria in the capability document (already in your
  context). Reference your EngagementPlan to recall what you expected from this committee.
  Do not advance if adequacy criteria are not met. Do not retry more than three times
  on the same committee without asking the operator.

  == EngagementPlan ==
  When briefing is complete, emit the EngagementPlan via the submit_plan tool (schema
  validated by the harness). The recon objective is concrete; downstream committee
  objectives may be provisional — you refine each at its gate via advance(next_objective).
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

== Committee digest ==
<leader summary + harness-derived adequacy fields — full artifact via read_artifact(name)>

Evaluate against adequacy criteria for the <committee> committee.
Use advance(next_objective), retry(note), iterate(note), or ask_operator(question).
```

The orchestrator already has `capability.md` and the EngagementPlan in context from
the briefing. Only the new artifact and gate prompt need to be injected.
Prior gate decisions and artifacts remain visible — the orchestrator sees the full
engagement trajectory.

### Gate tools

Provided by the harness at gate callback time only — not available during briefing.

| Tool | Signature | Effect |
|------|-----------|--------|
| `advance` | `advance(next_objective: str \| None = None)` | Proceed to next committee, optionally refining the *next* committee's objective with what this artifact revealed (just-in-time; downstream EngagementPlan objectives are provisional). Close engagement if terminal. **Rejected if the artifact is `incomplete: true`** — must `retry`/`iterate`/`ask_operator`. See R6b. |
| `retry` | `retry(note: str)` | Failure retry — re-run fresh; note appended to objective list |
| `iterate` | `iterate(note: str)` | Iteration retry — re-run with prior artifact shown; note appended to objective list |
| `ask_operator` | `ask_operator(question: str)` | Pause pipeline; surface question via operator chat |
| `read_artifact` | `read_artifact(name: str)` | Pull a full on-disk artifact when the digest isn't enough to decide (R4). Read-only — not a gate decision. |

The harness switches tool availability between phases: no gate tools during briefing,
gate tools injected at each callback. This prevents the orchestrator from calling
`advance()` before any committee has run.

**Every gate call logs a one-line rationale** to the run log — `advance` included, not just
`retry`/`iterate` — so the full flow trajectory is replayable. This audit trail is the
deterministic-envelope counterweight to LLM-driven flow (**R2**).

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

The recon objective is concrete; **downstream committee objectives are provisional** — a preview
for the operator's approval that the orchestrator refines just-in-time at each gate via
`advance(next_objective)` (workflow-level just-in-time, mirroring the Step level).

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
      "objective": ["Map open ports and web paths on 10.0.1.5; flag any version disclosure."],
      "constraints": ["timing T2 or slower", "avoid /admin brute-force"],
      "emphasis": ["web application paths", "TLS configuration"]
    },
    "planning": {
      "objective": ["Prioritise actions targeting credential exposure and web misconfigurations."],
      "constraints": [],
      "emphasis": ["signal_critical observations from recon"]
    },
    "retrieval": {
      "objective": ["Execute approved actions; retrieve credentials or sensitive files if accessible."],
      "constraints": ["read-only database access"],
      "emphasis": []
    },
    "reporting": {
      "objective": ["Produce a formal report suitable for the client's security team."],
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

Begin: submit your first Step.
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

**Optional: `briefing_required` block**

A structured checklist of inputs the ensemble cannot run without. When present, the
orchestrator works through each field with the operator before calling `submit_plan`.

```yaml
briefing_required:
  - name: directory
    type: string
    example: /home/user/projects
    description: Absolute path to walk
  - name: extensions
    type: array
    example: [".py", ".md"]
    description: Extensions to count, each including the dot
```

Omit this block if all required inputs can be inferred from the operator's initial
message or are not critical to the ensemble starting correctly. When present, it also
serves as documentation for the ensemble author — a clear statement of what the ensemble
cannot run without.

---

## Committee Document Schema (three layers)

Each committee has three documents. Each has a distinct audience and scope.

### `leader.yml` — Manifesto

The leader's **identity and output contract**. Lives in the system prompt — always in
context, so keep it short (~400–600 tokens).

Contains: who the leader is, what the committee produces, its output contract (the artifact
it synthesises at `finish`), harness-interface tools (`record_observation`, etc.),
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
 for a consensus element (instances > 1) with judge: leader, this is the explicit evaluation criterion>
```

Serves two purposes:
1. Leader reads it before planning to know what brief to write for each element.
2. For a consensus element (`instances > 1`) with `judge: leader`, the adequacy criterion is the
   reference the leader uses when selecting among N candidate outputs.

**Model capability targets:**

| Layer | Model | Reason |
|-------|-------|--------|
| Committee leader | claude-sonnet-4-6 | Reads 3+ docs + artifacts, produces plan, judges compare candidates, writes final artifact |
| Reasoning specialist (consensus, instances > 1) | claude-haiku-4-5 or smaller | Narrow focused task; running 3× means cost matters |
| Tool-using specialist | claude-sonnet-4-6 or claude-haiku-4-5 | Needs reliable function calling |
| Foundation-Sec | foundation-sec-8b via Ollama | Domain-tuned; cannot call tools |

---

## Committee Execution — Iterative Re-Planning

Supersedes the earlier one-shot "two-phase" model. A one-shot plan cannot express intra-committee
data dependencies — `service_probe` needs the ports `network_scan` found (**R1**) — nor adapt to
surprises the plan never anticipated (an exposed `/.git/`). So the leader plans **just-in-time**:
it emits the *next* Step, sees its output, then emits the Step after that. There is **no full
upfront plan** — which is what makes R1's fix *structural*: a dependent Step's brief is always
written *after* the Step it depends on has run, so it can never be written blind.

The committee's goal *is* its **objective** — the `objective` from the EngagementPlan's
`CommitteeBrief`. `finish` is judged against it.

The leader never touches an element directly — it declares a Step and the harness executes it.

**Schema** (`src/athena/committees/plan.py` — harness-level, not ensemble-specific):

```python
class CommitteeTask(BaseModel):
    element: str   # element id declared for this committee in the manifest
    brief:   str   # leader-written assignment; written with prior-step results in hand

class CommitteeStep(BaseModel):
    id:          str                    # harness-assigned UUID, stamped on submission
    description: str
    tasks:       list[CommitteeTask]    # the parallel unit (executed sequentially for now)
    supersedes:  list[str] = []         # ids of prior Steps this Step re-runs / replaces
```

The leader emits **one Step at a time** — never a whole plan. The harness stamps each submitted
Step with a UUID `id` and returns it alongside the Step's output, so the leader can name a prior
Step in a later Step's `supersedes`. Steps are sequential; **Tasks within a Step are the parallel
unit** (fan-out deferred — Tasks run sequentially for now).

**Leader tools (harness-provided):**

| Phase | Tool | Purpose |
|-------|------|---------|
| Start | `refuse_start(reason)` | The assigned objective is unclear. The harness surfaces the reason to the operator as a message and the engagement halts — the operator can abort (close the window). No re-briefing loop. |
| Loop  | `submit_step(step)` | Emit the next Step (`description` + `tasks`, optional `supersedes`). Harness validates (element ids exist), stamps a UUID, executes it, returns its output. Submitting the next Step *is* the re-plan — it is written with all prior results in hand. |
| Loop  | `ask_operator(question)` | Proactively pause for operator help — surface, wait, inject the reply, continue. *When* to ask is set in the playbook's escalation criteria (see **Operator Interaction**). |
| Loop  | `reply_operator(message)` | Answer an operator chat message without advancing work. |
| Loop  | `finish()` | The objective is met → synthesise the committee artifact from all non-superseded Step outputs. |

There is **no per-element summon tool, and no separate `continue`/`revise`** — submitting the next
Step is both planning and advancing. The only execution affordance is a whole Step (a batch); the
playbook instructs the leader to batch genuinely independent work into one Step. This costs **one
leader call per Step** — accepted, as the price of per-step adaptivity.

**Loop:**
1. **Start.** Leader reads playbook + task cards + brief. If the objective is unclear →
   `refuse_start`. Otherwise → `submit_step` (the first Step). A clear objective is a hard
   precondition — it is what makes `finish` definable.
2. **Execute.** Harness runs the Step's Tasks (sequentially for now) and appends the output
   (tagged with the Step's UUID) to the leader's context.
3. **Leader turn.** `submit_step` (the next Step, written with results in hand) or `finish`.
   Operator interrupts (`[OPERATOR INTERRUPT]`) arrive here, between Steps.
4. Repeat until `finish` or the Step cap.

**Supersession (stale-output handling).** When a `submit_step` re-runs earlier work (e.g. a
re-scan on operator request), it lists the superseded Step ids in `supersedes`; the harness drops
those Steps' outputs from the synthesis context, so the committee artifact never carries stale,
superseded data. A Step that only advances the work supersedes nothing. Mirrors the
committee-level rule (a back-edge retry overwrites the committee artifact) one level down.

**Ending the committee.** The leader `finish`es when the **objective** is met, judged against the
objective + the adequacy criterion in its task cards / playbook. The orchestrator then
*independently* re-checks adequacy at the committee gate (`advance`/`retry`/`iterate`).

**Step cap (intra-committee R3).** Hard ceiling on Steps per committee run. Harness default,
overridable per committee in the manifest (`max_steps:`). Default: **12**. Reaching the cap
force-synthesises an artifact marked `incomplete: true` — see **R6b (incomplete artifacts)**.

**Known trade (challenge #1):** just-in-time softens the *hard* anti-greedy guarantee of one-shot
into *soft* discipline — a lazy leader could emit one-task Steps, i.e. the reactive spiral in
disguise. Mitigation, not elimination: no per-element summon tool (only whole Steps), a playbook
that demands batching, and the hard Step cap.

---

## Task Document (`task.md`)

See **Committee Document Schema → task.md** above for the full format specification
and the assignment template standard.

For a consensus element (`instances > 1`), the adequacy criterion section doubles as the judge criterion —
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
- **Limit: 30 iteration retries per committee** (reduced from 150 while nesting is unbounded).
  Note this nests with the intra-committee **Step cap (12)** — worst case ≈ 30 × 12 = 360 Steps
  per committee — so a per-engagement global ceiling that spans the nesting is still the real
  backstop (**R3**, open). Count is injected into the gate callback for transparency.

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

This is a [retry / refinement]. Resume just-in-time — submit your first Step.
```

---

## Operator Interaction

Operator messages carry a **type**, so the harness routes them correctly:

- **chat** → the committee leader. Delivered as `[OPERATOR INTERRUPT]` at the leader's next Step
  boundary; the leader answers via `reply_operator(message)` and continues. (For the demo,
  acknowledgement at the next Step is fine.)
- **flow directive** ("halt and proceed", "add a gate before planning") → the orchestrator, since
  flow is its domain (see Halt and Ad-hoc gates below).
- **steering hint** ("focus on the database") → the committee leader, folded into its next Step.

**Committee `ask_operator`.** The leader may proactively pause for help via `ask_operator(question)`
— surface, wait, inject the reply, continue. *When* to ask is authored in the committee's playbook /
`capability.md` as explicit escalation criteria ("ask the operator if: an action looks destructive;
the objective is ambiguous; two viable paths and no basis to choose; a critical finding warrants a
call"). Mirrors the orchestrator's own `ask_operator`, one level down.

**Halt (force-finish).** A single harness primitive forces a running leader to `finish` with what
it has (→ its gate fires early). It underlies the operator "halt and proceed", the Step-cap
force-synthesis, and the 200-Step budget halt. **Operator-initiated only for now**; the resulting
artifact is tagged `operator_directive: advance`, which authorises the gate to `advance` and
overrides R6b (the operator owns the truncation). Orchestrator-initiated mid-committee halt is the
same primitive with a wake trigger — deferred.

**Step hijack.** By default the operator is heard at Step boundaries. A *priority* message can be
honoured between a Step's Tasks (Tasks run sequentially now) — the harness stops before the next
Task, returns the partial Step + the message to the leader, which re-plans (and may `supersedes`
the partial Step). Aborting a Task with an in-flight network call is out of scope.

**Ad-hoc gates.** An operator can add an approval gate mid-run via a flow directive ("approve
before planning"); since the orchestrator evaluates at every boundary, it honours it as an
`operator_approval` pause there. Requested during briefing, the same gate is a first-class
`EngagementPlan.gates` entry.

---

## Output Contracts

Pydantic schemas in `schemas/`. One per committee, declared in the manifest.
The harness validates committee output against its schema before passing it downstream.
Type errors surface at the committee boundary, not inside the next committee's processing.

On retry (back-edge): the committee's artifact is **overwritten** by the new run.

**Output directives (e.g. report format).** Per-committee formatting/emphasis — "structure the
report as MITRE ATT&CK, map each finding to a technique ID + tactic" — is set in the reporting
`CommitteeBrief` during briefing. The brief *is* the customization surface; no special mechanism.
The `ReportOutput` schema's freeform `sections` hold a MITRE technique-mapping table for the demo;
a rigorous version adds optional `technique_mappings: [{finding, technique_id, tactic}]`.

---

## Knowledge Granules

Knowledge is read-only reference material a specialist consults during its task — distinct
from a skill's world-changing action. It is modeled as a **read-only retrieval skill**: the
specialist sees a lookup callable, only the retrieved result enters context (not the whole
corpus), and every retrieval is logged so the audit trail stays intact.

### Choosing a backing store

| Shape of the knowledge | Mechanism |
|------------------------|-----------|
| Small + always relevant (playbook-scale) | Read the file into context directly |
| Structured / keyed (CVE-by-version, ATT&CK-by-id) | Deterministic lookup over a flat file or SQLite index — more precise and auditable than vector search |
| Large + unstructured + needs semantic match (report libraries, prose corpora) | Embeddings / RAG, behind the same logged retrieval skill |

Prefer files and structured indexes; reserve embeddings for corpora that genuinely cannot
be injected and are not keyed. Files and SQLite indexes are portable for distribution; a
vector store adds an embedding-model dependency and a build/ship step.

### Declaration and wiring

Knowledge granules follow the skill model. A granule is declared in a `knowledge:` registry
in `manifest.yml` and granted to an element the same way skills are — via a `knowledge: [...]`
list on the element entry. Specialist-specific knowledge may instead be declared inline in
the specialist's own `.yml`, with its corpus co-located (mirroring agent-level skills). The
declaration's `description` is the *access instruction* — what the granule knows and when to
consult it — the same role a skill's description plays for the LLM.

```yaml
# in manifest.yml
knowledge:
  - id: cve_lookup
    definition: knowledge/cve_lookup/knowledge.yml
    store: sqlite                       # file | sqlite | embeddings
    corpus: knowledge/cve_lookup/cve.db

committees:
  recon:
    elements:
      - id: threat_analysis
        knowledge: [cve_lookup]         # surfaces to the specialist as a read-only lookup skill
```

### For the red-teaming ensemble

Its knowledge candidates (CVE-by-service/version, ATT&CK technique mappings) are structured
→ deterministic lookup skills. No embeddings for this ensemble.

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

The harness derives terminality from the transitions list: a committee is terminal when
it has no forward edges (no `to:` pointing at a different committee). Self-loops
(`condition: retry` / `condition: iterate`) do not make a committee non-terminal.
After every `advance()` call the harness checks:
- Forward edge exists → look up next node, spawn next committee
- No forward edge → close the engagement

`advance()` at the terminal node means "done" rather than "proceed." No new tools or
special cases — the orchestrator calls the same four gate tools at every boundary.
The harness determines the outcome of `advance()` from the graph position.
The orchestrator may still call `iterate(note)` or `ask_operator` at the terminal
boundary before choosing to advance.

---

## Not Yet Designed — Ensemble Layer

- **Ensemble registry / database** — how the orchestrator discovers and selects ensembles.
  Deferred: while red-teaming is the only ensemble, `latest` = the only version present and
  the one ensemble is hand-loaded.
- **Ensemble distribution** — how ensembles are packaged, published, and installed from the
  marketplace. Deferred with the registry.

## Designed, Not Yet Implemented

- **Knowledge granules** — design captured under **Knowledge Granules** above. No granule is
  wired into the red-teaming manifest yet (candidates: CVE-by-version, ATT&CK lookups).
- **Parallel task execution (fan-out/fan-in)** — Tasks are the parallel unit (see **Committee
  Execution — Iterative Re-Planning**), but fan-out is deferred; the harness runs Tasks
  sequentially for now. Task-level fan-out is the agreed target.

---

## Demo vs. Real-World Scope

Several design points have a clean real-world answer and a simpler demo answer. The demo
(Linux Apache → exposed `credentials.json` → Postgres rows) uses the simpler form; the
real-world form is the target.

| Concern | Real-world (target) | Demo (now) |
|---|---|---|
| **Target-type specialization** | Recon fingerprints the OS first, then the leader selects OS-appropriate teams (a Windows Network Team probes SMB/RDP/WinRM/LDAP; a Linux one probes ssh/http/tls). | Linux teams hardcoded; no OS-detection step. |
| **Team autonomy** | A Team is an autonomous **sub-committee** — its Team Leader dynamically forms and sequences the element grouping it needs from an IP-level brief. Committee and Team are one recursive primitive. | Flat: committees hold leaf elements; the committee leader sequences/aggregates; no team leaders. |
| **Packaging granularity** | A packaged/swappable unit could be an element, a team, or a committee (per-OS committees, marketplace-installable teams). | Packaging stays at the **committee** level; the red-teaming ensemble is a fixed set of committees. |

Dynamic team formation (a Team Leader composing elements) is *constrained* composition — it
selects from the ensemble's fixed element catalog, not arbitrary spawning. Still, the ensemble
direction as a whole is a conscious relaxation of the original "committees hardcoded in Python"
rule (AGENTS.md rule 2) — the same posture shift as **R2**, to be acknowledged, not drifted into.

---

## Design Risks

Risks inherent to the ensemble design (excluding the deferred features above). Each carries a
proposed mitigation and a status: **DECISION** (needs a design call) or **PROPOSED** (mitigation
agreed in principle, to implement).

**R1 — Two-phase leader vs. intra-committee data flow.** _(RESOLVED — model changed)_
The one-shot two-phase model authored the whole plan before any element ran, so dependent
steps were written blind (`service_probe` couldn't know the ports `network_scan` would find)
and, worse, could not adapt to unplanned surprises. Resolved by **just-in-time** step emission —
see **Committee Execution — Iterative Re-Planning**. The leader emits one Step at a time, so a
dependent Step's brief is always written *after* the Step it depends on has run. There is no
full upfront plan to write blind, which makes the fix **structural** — it does not rely on the
leader choosing to revise. Superseded both the one-shot model and the lighter "thread outputs
into a fixed plan" patch (which would have fixed data flow but not adaptivity, and left the fix
soft).

**R2 — Flow control is LLM-driven (posture shift).** _(RESOLVED — posture accepted)_
advance/retry/iterate/loop-back are orchestrator LLM judgments against prose adequacy criteria,
inverting the old "orchestrator sequencing is deterministic" principle (AGENTS.md rule 5).
**Accepted posture:** flow is LLM-driven within a **deterministic envelope** — (1) the LLM may only
choose among **manifest-declared transitions** (it cannot invent an edge), (2) hard budgets (R3)
bound every loop, and (3) **every gate call logs a one-line rationale** for a fully auditable
trajectory. What is *reachable* stays deterministic and author-owned; only *which reachable path*
is the LLM's call — bounded and logged. A conscious, recorded departure from the old charter.

**R3 — Loops bounded only by soft limits.** _(RESOLVED)_
`iterate` is 30 and the Step cap is 12, but they nest. The ultimate backstop is a **global
per-engagement budget of 200 total Steps** across all committees and their retries/iterations —
when hit, the harness halts the engagement and surfaces it to the operator. Additionally:
validation re-inject loops are capped (3 → fail), and the `retry` cap of 3 is mechanically
enforced (`ask_operator` required after). No unbounded loop anywhere.

**R4 — Orchestrator context grows monotonically.** _(RESOLVED)_
The conversation stays open across the whole engagement; every artifact + retry is injected →
context-window pressure, lost-in-the-middle, rising per-gate cost. Resolved by keeping the
trajectory visible but not resident:
1. **Digest, not artifact.** Each gate injects a compact committee **digest** — the leader's short
   summary + harness-derived adequacy fields (recon → highest classification + counts; plan →
   action count + top priority; report → `risk_rating`). The digest must be **accurate and to the
   point** — it *is* the basis for the adequacy decision. Digest fields are chosen per committee,
   next to its output schema.
2. **`read_artifact(name)`** — the orchestrator pulls the full on-disk artifact on demand when the
   digest isn't enough; nothing is lost, just not resident.
3. **Drop superseded digests** — on retry/iterate keep only the latest digest + an "attempt N of M"
   marker, not one per attempt.
Result: orchestrator context stays roughly flat regardless of engagement length (`capability.md` +
EngagementPlan + ~4 live digests + the gate-rationale trail), and adequacy judgment sharpens (the
relevant fields are front-and-centre, not buried in a full artifact dump).

**R5 — Typed at the boundary, untyped in consumption.** _(RESOLVED)_
Output schemas validate production, not that the next committee correctly *reads* the artifact
(injected as prose) — a schema change can silently break a downstream consumer. Resolved by:
1. **Canonical per-schema renderer** (bundled in `schemas/`) — one deterministic rendered shape
   downstream committees see; versions in lockstep with the schema; also the source of R4's digest.
2. **Per-committee contract-test fixtures** — each committee ships a representative upstream
   artifact; a test asserts it still produces valid output, turning a silent consumption break into
   a build-time failure. (The load-bearing part — the renderer controls format, the fixture catches
   whether the consumer still works.)
3. **Version containment** — A's schema + renderer + B's consumption ship together in one ensemble
   version; the fixtures guard each version.

**R6 — Leader is the only judge, and does double duty.** _(RESOLVED)_
Consensus quality (`instances > 1`) rested on the leader both selecting among N candidates and
synthesising, with only a prompt instruction as guard. Resolved by separating *select* from
*synthesise* and moving enforcement to Python:
- **Select (leader path):** the leader returns only `{element_id, chosen_candidate_id, reason}` — it
  *points* at a candidate, never re-writes one. The harness **validates the id is one of the N**
  (rejects an invented "third option") and resolves it to the candidate's **verbatim** text.
- **Select (scorer path):** a deterministic Python scorer picks the top candidate against objective
  `task.md` criteria — no LLM in the selection. Preferred where the criterion is objective.
- **Synthesise:** the committee artifact is a separate `finish` step, never conflated with selection.
The LLM only ever *points* (or Python scores); Python owns validation and holds the bytes.
(`agent` judge still deferred.)

**R6b — "Incomplete" committee artifacts have no enforced handling.** _(RESOLVED)_
When the Step cap is hit, the harness force-synthesises an artifact marked `incomplete: true`.
**Rule:** an `incomplete: true` artifact **cannot `advance`** at its gate — the harness rejects
`advance()` on it, so the orchestrator must choose `retry` / `iterate` / `ask_operator`. This
makes incompleteness mechanical: a committee that ran out of Steps can never silently pass a
truncated artifact downstream as if it were done.

**R7 — Element-consensus SIEM-safety is not mechanically enforced.** _(ACCEPTED — author responsibility for now)_
`instances > 1` multiplies execution and is only safe on non-traffic elements. The harness does not
verify this; the ensemble **author** configures `instances`/`skills` with the domain knowledge and
**owns the consequence** — a misconfigured consensus on a tool-using element trips the author's own
SIEM against their own target. Acceptable while **author = operator** (self-authored ensembles, the
demo and near term). **Deferred to distribution:** once ensembles are shipped by third parties
(author ≠ operator), a misconfigured/malicious ensemble would multiply the *operator's* traffic
without their knowledge — there the harness must enforce it (a per-skill `external: true|false`
marker; reject `instances > 1` on any `external` skill). Same "author ≠ operator" class as **R8**;
folds into the deferred distribution/trust work.

**R8 — The manifest is a code-execution surface.** _(ACCEPTED — author-trusted for now)_
`impl: path::function` loads and runs arbitrary Python at load time. For **self-authored,
well-vetted** ensembles (demo and near term) this is your own code — not a threat. Same
"author = operator" reasoning as **R7**. **Deferred to distribution:** running a third party's
`impl.py` (author ≠ operator) needs a real trust model — signing, sandboxing, review, and
constraining `impl` resolution to the ensemble dir / an allowlisted root — a hard prerequisite
before any marketplace install. Folds into the deferred distribution/trust work.

**R9 — Live-findings UX (migration).** _(RESOLVED — migration requirement)_
The demo's live criticals came from incremental `record_observation` during the leader's synthesis
loop — the iterative model keeps that synthesis step, so the effect ports over. Requirement:
(1) Step execution fires `agent.spawned`/`agent.tool_called` so the graph is animated throughout
recon; (2) synthesis (`finish`) fires `agent.finding` **incrementally** (per finding), not as a
batch, so criticals stream in as classified; (3) optional interim raw-finding event per Step for
earlier signal. Not a design change — a harness event-emission checklist item. The broader event
taxonomy has changed; the UI needs a rework — see **ENSEMBLE_UI.md**.

**R10 — "Team" is vestigial.** _(WITHDRAWN)_
Superseded by the clarified model: Team is the first-class **breadth** level — N different
elements the committee leader combines (e.g. a Network Team of ssh/tcp/http elements) — distinct
from Element's **depth** (temperature consensus over one task). Not vestigial. For now the
committee leader is the team aggregator (no team-level agent). See **Vocabulary → Team**.

---

## Open Issues — `_inventory` Reference Ensemble

Small defects remaining in `202607/_inventory/ensembles/inventory/1.0.0/` after the 2026-07-23
audit. Address before using `_inventory` as the Phase 1 build target.

**I1 — `capability.md` missing `briefing_required` block** _(Open)_
The `briefing_required` format is now specified in **Capability Document** above. The inventory
`capability.md` does not yet have one. Add:
```yaml
briefing_required:
  - name: directory
    type: string
    example: /home/user/projects
    description: Absolute path to walk
  - name: extensions
    type: array
    example: [".py", ".md"]
    description: Extensions to count, each including the dot
```

**I2 — `capability.md` "Ask the operator if" conflates briefing-time and gate-time** _(Open)_
The section currently lists "The directory is missing" and "No extensions were provided" — both
are conditions the orchestrator resolves *during briefing* (covered by `briefing_required`), not
at a gate callback after a committee has run. Split or rewrite: briefing-time conditions belong
in `briefing_required`; gate-time escalation criteria (e.g. "zero files counted across all
extensions despite a valid directory") belong in "Ask the operator if."

**I3 — `report/leader.yml` tool list is parenthetical** _(Open)_
`scan/leader.yml` has an explicit `== Loop ==` section listing each tool on its own line with its
effect. `report/leader.yml` lists the tools only as an inline parenthetical
`(submit_step / finish / refuse_start / ask_operator / reply_operator)`. Bring it into the same
format as `scan/leader.yml` for consistency.

**I4 — `report/playbook.md` has no escalation criteria** _(Open)_
The scan playbook says "ask_operator to confirm the path or the extension list" when a zero total
is returned. The report playbook has no equivalent "When to adapt / ask_operator" guidance.
For a simple committee this is low risk, but it is asymmetric with the scan playbook. Add at
minimum: when to call `ask_operator` if the ScanOutput looks malformed or empty.
