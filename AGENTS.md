# AGENTS.md — Athena

> Standing instructions for any coding agent (OpenCode, Claude Code, Codex, etc.)
> working in this repo. Read this fully before making changes. These rules hold
> regardless of which model is driving.

## What this project is

Athena is a proof-of-concept **agent committee pipeline**: a human issues one
high-level instruction, an orchestrator summons specialist committees that each do a
phase of work, produce an artifact, hand it to the next committee, and spin down. The
demo theme is a simplified, fully-benign red team engagement (recon → planning →
retrieval → reporting). The point being validated is the **orchestration paradigm**, not
red teaming.

**Before any architectural decision, read `PLAN.md` and `DESIGN.md` if present.**
Before building the current slice, read the active phase prompt if present (e.g.
`CLAUDE_CODE_ATHENA_RECON.md`). Build only what the current phase prompt covers.

## Non-negotiable rules

1. **NO offensive / exploit code, ever.** Agents use services exactly as configured. No
   vulnerability exploitation, CVE usage, auth bypass, injection, fuzzing, or
   path-traversal attempts. Recon may perform bounded service inventory against the
   configured local target using normal handshakes and metadata reads only. The
   "retrieval" committee is strictly an HTTP client that GETs a file an
   intentionally-misconfigured server openly serves — it uses the service as designed and
   never subverts it. **If any requested feature would drift toward offensive capability,
   STOP and flag it instead of building it.**

2. **Build ONE committee at a time.** Do not build ahead of the current phase prompt.
   Phase 1 is Recon only; Planning, Retrieval, and Reporting come in later phases. Do not
   scaffold committees the current phase doesn't ask for.

3. **No dynamic agent spawning, no agent frameworks, no managed agent platforms.**
   Committees are hardcoded and pre-configured. Do not introduce LangGraph, agent
   platforms, or similar. The agent loop is hand-written.

4. **The agent loop stays small and readable (~40–60 lines), and clearly commented.** It
   is the core primitive a first-time agent builder must understand line by line. Do not
   abstract it into something clever.

5. **Model access goes through the swappable `ModelBackend` interface only.** No direct
   SDK calls outside the backend implementation. API key comes from an environment
   variable (`ANTHROPIC_API_KEY` or the configured provider's var), never hardcoded,
   never logged.

6. **Deterministic Python wraps the fuzzy LLM (System 1 / System 2).** The reliable,
   auditable parts — orchestrator sequencing, artifact-schema validation, tool scoping,
   the human-review gate, max-iteration caps — are deterministic code, not behaviors we
   hope the LLM exhibits. The LLM proposes; deterministic logic disposes.

7. **Tool scoping is the security boundary.** Each committee gets only the tools its job
   requires. Recon is allowed only bounded local inventory tools: `check_port`,
   `http_head`, `http_get`, `tls_probe`, `ssh_banner`, `tcp_banner`, `nmap_scan`, and
   `extract_links`. Retrieval remains `http_get`; Reporting remains `read_artifact` +
   `write_file`. Do not widen a committee's tool set without being asked. Never add a
   tool that performs offensive action.

8. **`nmap` is allowed only through a deterministic wrapper.** The LLM must never build
   or execute arbitrary `nmap` commands. The wrapper may scan only the configured local
   target, with approved flags, hard timeouts, no NSE scripts, no OS fingerprinting, no
   UDP scans, no evasion flags, no brute-force checks, and no vulnerability or exploit
   scripts. The port scope is a hardcoded common-port range inside the wrapper — the
   caller (including the LLM) cannot supply or influence which ports are scanned.

9. **Everything runs locally via docker-compose.** The only target is the target
   container or authorized target VM in this stack. No cloud, no real external targets.

## Conventions

- **Language:** Python 3.11+, async where it genuinely helps.
- **Schema:** pydantic for the shared artifact schema (the pipeline backbone). Every
  committee reads the prior artifact and emits the next; the hand-off chain must be
  traceable (every artifact references what it consumed and produced).
- **Lint/format:** ruff + black; type hints throughout.
- **Infra:** docker-compose from the start (runner container + target container or
  authorized target VM on a shared network).
- **Output:** artifacts and run logs written to a mounted `./artifacts` volume.
- **Determinism:** the target is fixed/configured so demo runs look the same each time.

## Doc discipline

- `PLAN.md` changes when the current **build plan** changes.
- `DESIGN.md` changes when the broader **strategy/architecture** changes, if present.
- The phase prompts (e.g. `CLAUDE_CODE_ATHENA_RECON.md`) change when the **build slice**
  changes.
- `AGENTS.md` (this file) changes when the **rules** change.
- `README.md` indexes everything.
- Do not edit a doc to match code you wrote; if code and a doc conflict, STOP and flag it.

## Build & run

- Bring up the stack: `docker-compose up`
- Set credentials: copy `.env.example` to `.env` and add the API key.
- Expected run: the orchestrator summons committees; the run log legibly shows each
  committee summoned → working → artifact emitted → spun down; artifacts land in
  `./artifacts`.
- (Fill in concrete test commands here as they are created — do not invent commands that
  don't exist yet.)

## When in doubt

Prefer the smallest change that satisfies the current phase. Surface uncertainty and
conflicts rather than guessing. Never trade away the no-offensive-code rule, the
one-committee-at-a-time rule, or the readability of the agent loop for convenience or
speed.
