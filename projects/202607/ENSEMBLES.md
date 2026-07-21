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
          leader.yml        # leader system prompt + model
          elements/
            <element-id>/
              task.md       # static: what this element produces (used as compare criterion)
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

## Engagement Plan

The orchestrator produces an `EngagementPlan` at the end of the briefing dialogue.
The operator reviews and approves it (the existing Proceed button is the approval gesture).
`runner.py` reads the plan before the committee pipeline starts and uses it to:
- Wire approval gates at the declared phase transitions
- Build the per-committee brief passed to each leader at spawn time

```yaml
# EngagementPlan structure (produced by orchestrator at end of briefing)
engagement_id: ...
operator_instructions: "<verbatim operator request>"

committees:
  recon:
    objective: "<specific objective for this committee, this engagement>"
    constraints:
      - "<e.g. avoid aggressive scan patterns>"
    emphasis:
      - "<e.g. web application paths>"

  planning:
    objective: "..."
    constraints: []
    emphasis: []

  retrieval:
    objective: "..."
    constraints: []
    emphasis: []

  reporting:
    objective: "..."
    constraints: []
    emphasis: []

gates:
  - after: recon
    type: orchestrator_review     # orchestrator evaluates output before advancing
  - after: planning
    type: operator_approval       # operator must approve before retrieval starts
```

When spawning a committee leader, the harness builds its initial brief as:

```
== Engagement brief for your committee ==
Objective: <objective>
Constraints: <constraints>
Emphasis: <emphasis>

== Prior committee outputs ==
<upstream artifacts>

Begin.
```

**Key property:** the orchestrator's reasoning is front-loaded into the plan.
The harness executes the plan mechanically. The orchestrator only re-engages
mid-pipeline if the graph rules trigger a retry or an operator-directed intervention.

---

## Capability Document (`capability.md`)

Read by the orchestrator at ensemble load time. Written by the ensemble author.
The orchestrator never reads `task.md` files (those are committee-internal).

Must contain:
- What the ensemble does and what it produces
- Per-committee description: inputs, outputs, what "adequate" looks like
- When to advance vs. retry vs. ask the operator
- Model notes (e.g. Foundation-Sec cannot call tools)
- Engagement constraints (allowlists, read-only enforcement)

---

## Task Document (`task.md`)

Static file shipped with each element. Read by the committee leader, not the orchestrator.
Describes what the element is meant to produce in abstract terms.

Serves two purposes:
1. The leader reads it to understand what each element can produce before assigning work.
2. In `compare` mode with `judge: leader`, it is the reference criterion for evaluation.

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

## Not Yet Designed

- **Knowledge granules** — declaration format, injection mechanism, candidates for this ensemble.
- **Ensemble registry / database** — how the orchestrator discovers and selects ensembles.
- **Parallel element execution** — elements within a team currently run sequentially.
  True fan-out/fan-in (Goal 2b) is a prerequisite for realising the full team model.
- **Ensemble distribution** — how ensembles are packaged, published, and installed from the marketplace.
