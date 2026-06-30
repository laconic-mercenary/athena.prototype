# Athena

A proof-of-concept for an **agent committee pipeline**: you give one high-level instruction,
an orchestrator summons specialist committees that each do a phase of work, produce an
artifact, hand it to the next, and spin down. The demo theme is a simplified, fully-benign
red team engagement (recon → planning → retrieval → reporting) — but the point is the
**orchestration paradigm**, not red teaming.

> **Status:** concept PoC, built one committee at a time. Currently: Phase 1 (Recon).

## What this is (and isn't)

- **Is:** a clean demonstration that committees can be summoned, do real work, hand off
  artifacts, and spin down — coordinated by an orchestrator, with a traceable artifact chain.
- **Isn't:** an offensive tool. It contains no exploitation of any kind. Agents use services
  as configured; Recon performs bounded local service inventory only, and the "retrieval"
  committee is a plain HTTP client retrieving a file a misconfigured server openly serves.
  (See `PLAN.md` and `AGENTS.md`.)

## Files

| File | For | Purpose |
|------|-----|---------|
| **README.md** | Everyone | This index. |
| **PLAN.md** | Team / reviewers | Current build plan: component order, bounded Recon scope, strict `nmap` wrapper, and Phase 1 implementation boundaries. |
| **DESIGN.md** | Team / reviewers | Intended overall design doc for the full four-committee pipeline. Not currently present in this repo. |
| **CLAUDE_CODE_ATHENA_RECON.md** | Coding agent | The build spec for the current phase (scaffold + target + Recon). Read for *how*, this slice. |

## Run (once built)

```
cp .env.example .env   # add ANTHROPIC_API_KEY
docker-compose up
```
Brings up the benign target VM/container and runs the orchestrator. Watch the lifecycle log:
committee summoned → working → artifact emitted → spun down. Artifacts land in ./artifacts.

## Build approach

One committee at a time, docker-compose from the start, verify each phase before the next.
Phase 1 is Recon; phases 2–4 replicate the same pattern (role prompt + scoped tools + agent
loop + emit artifact) for Planning, Retrieval, Reporting. See `PLAN.md`.

## The one rule that matters most

No offensive/exploit code, ever. Agents use services as configured. If a feature would drift
toward offensive capability, stop and flag it. Recon can gather local service metadata only
through approved bounded tools, including a deterministic `nmap` wrapper.
