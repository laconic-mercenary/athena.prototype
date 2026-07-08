# AGENTS.md — Athena

> Standing instructions for any coding agent (Claude Code, OpenCode, Codex, etc.)
> working in this repo. Read this fully before making changes. These rules hold
> regardless of which model is driving.

## What this project is

Athena is a proof-of-concept **agent committee pipeline**: a human issues one high-level
instruction, an orchestrator summons specialist committees that each do a phase of work,
produce an artifact, hand it to the next committee, and spin down. The demo theme is a
simplified, authorized red team engagement (recon → planning → retrieval → reporting).
The point being validated is the **orchestration paradigm**, not red teaming.

All four committees are implemented and running end-to-end. See `ATHENA_README.md` for the
full architecture and `projects/FOUNDATION_MODELS_PLAN.md` for the Foundation-Sec
integration.

---

## Non-negotiable rules

1. **NO offensive / exploit code, ever.** Agents use services exactly as configured. No
   vulnerability exploitation, CVE usage, auth bypass, injection, fuzzing, or
   path-traversal attempts. Recon performs bounded service inventory against the
   configured local target using normal handshakes and metadata reads only. The
   Retrieval committee is strictly an HTTP client and Postgres client using credentials
   the intentionally-misconfigured server openly serves — it uses the services as
   designed and never subverts them. **If any requested feature would drift toward
   offensive capability, STOP and flag it instead of building it.**

2. **No dynamic agent spawning, no agent frameworks, no managed agent platforms.**
   Committees are hardcoded and pre-configured. Do not introduce LangGraph, agent
   platforms, or similar. The agent loop is hand-written.

3. **The agent loop stays small and readable (~40–60 lines).** It is the core primitive
   a first-time agent builder must understand line by line. Do not abstract it into
   something clever.

4. **Model access goes through the swappable `ModelBackend` interface only.** No direct
   SDK calls outside the backend implementation. API keys come from environment variables
   only (via `.env` loaded at startup), never hardcoded, never logged.

5. **Deterministic Python wraps the fuzzy LLM.** The reliable, auditable parts —
   orchestrator sequencing, artifact-schema validation, tool scoping, the human-review
   gate, max-iteration caps — are deterministic code, not behaviors we hope the LLM
   exhibits. The LLM proposes; deterministic logic disposes.

6. **Tool scoping is the security boundary.** Each committee gets only the tools its job
   requires:
   - Recon operators: `check_port`, `http_head`, `http_get`, `tls_probe`, `ssh_banner`,
     `tcp_banner`, `nmap_scan`, `extract_links`
   - Recon leader: `summon_operator` (Phase 3 follow-up only)
   - Retrieval: `http_get`, `postgres_query`
   - Reporting: `read_artifact`, `write_file`
   Do not widen a committee's tool set without being asked. Never add a tool that
   performs an offensive action.

7. **`nmap` is allowed only through a deterministic wrapper.** The LLM must never build
   or execute arbitrary `nmap` commands. The wrapper scans only the configured local
   target, with approved flags, hard timeouts, no NSE scripts, no OS fingerprinting,
   no UDP scans, no evasion flags, and no vulnerability or exploit scripts.

8. **Everything runs against the local Docker target only.** No cloud, no real external
   targets. The only target is the container in `docker-compose.yml`.

---

## Current architecture

### Committees and agents

**Recon committee** (`src/athena/committees/recon.py`)

Four-phase flow driven by Python:

| Phase | Who | What |
|-------|-----|------|
| 1 | `network_operator`, `service_operator`, `web_operator` (Claude) | Parallel operator runs — port scan, service banners, web enumeration |
| 2 | `threat_analyst` (Foundation-Sec-8B) | Pure reasoning — CVE candidates, risk indicators, bulleted markdown output, no tools |
| 3 | `leader` (Claude Sonnet) | Optional follow-up via `summon_operator` based on analyst recommendations |
| 4 | `leader` | Synthesises full `ReconArtifact` JSON |

The leader never participates in Phase 1. Python iterates `_DEFAULT_TASKS` and calls
`_run_operator()` directly. The leader receives all findings pre-gathered in its initial
message context.

Foundation-Sec outputs bulleted markdown (`## CVE Candidates`, `## Risk Indicators`,
`## Recommended Follow-up`, `## Assessment`). The Python layer stores this as
`ThreatAnalysis(summary=raw_text)` and passes it verbatim to the leader.

**Planning committee** (`src/athena/committees/planning.py`)  
Leader (Claude Sonnet) + `network_planner`, `web_planner`. Reads `ReconArtifact`,
emits `PlanArtifact` with prioritised actions.

**Retrieval committee** (`src/athena/committees/retrieval.py`)  
Leader (Claude Sonnet) + `web_retriever`, `db_specialist`. Executes plan actions,
emits `RetrievalArtifact`.

**Reporting committee** (`src/athena/committees/reporting.py`)  
Leader (Claude Sonnet) + `findings_analyst`, `risk_assessor`. Synthesises all prior
artifacts into a `ReportArtifact` with risk rating, sections, and recommendations.

### Key modules

| Module | Responsibility |
|--------|----------------|
| `src/athena/main.py` | CLI entrypoint — loads `.env`, parses args, calls orchestrator |
| `src/athena/config.py` | `load_config()` — parses `athena.yml` into `AthenaConfig` |
| `src/athena/schemas.py` | Pydantic artifact schemas for the full pipeline |
| `src/athena/model_backend.py` | `ModelBackend` interface; `AnthropicBackend`, `OllamaBackend`, `FakeBackend` |
| `src/athena/agent_loop.py` | Core agent loop — tool dispatch, iteration cap |
| `src/athena/tools.py` | Deterministic tool implementations |
| `src/athena/orchestrator.py` | Run lifecycle — approval gate → committee sequence |
| `src/athena/artifacts.py` | `RunLogger`, artifact file writes |

### Infrastructure

Foundation-Sec is hosted on Modal (A10G GPU) via vLLM. The deployment is in
`infra/modal/modal_serve.py`. `OllamaBackend` speaks to it via the OpenAI-compatible
`/v1/chat/completions` endpoint, with `OLLAMA_API_KEY` as a Bearer token.

---

## Conventions

- **Language:** Python 3.10+
- **Schema:** Pydantic for all artifacts — every committee reads the prior artifact and
  emits the next; the handoff chain is traceable (every artifact references what it consumed)
- **Lint/format:** ruff + black; type hints throughout
- **Infra:** docker-compose — runner environment + target container on a shared network
- **Output:** artifacts and run logs written to `./artifacts/<run_id>/`
- **Tests:** pytest, 93 tests; `FakeBackend` drives all committee and orchestrator tests —
  no live network calls in the test suite

---

## Doc discipline

- `ATHENA_README.md` — project overview, architecture, quick start
- `AGENTS.md` (this file) — standing rules and architecture reference for coding agents
- `projects/FOUNDATION_MODELS_PLAN.md` — Foundation-Sec evaluation and integration outcome
- Do not edit a doc to match code you wrote; if code and a doc conflict, STOP and flag it

---

## When in doubt

Prefer the smallest change that satisfies the task. Surface uncertainty and conflicts
rather than guessing. Never trade away the no-offensive-code rule or the readability
of the agent loop for convenience or speed.
