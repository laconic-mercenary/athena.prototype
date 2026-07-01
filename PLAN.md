# PLAN.md - Athena Build Plan

## Build Order

1. Project scaffold ✅
2. Authorized target VM ✅
3. Shared schemas ✅
4. Tool layer
5. Model backend
6. Agent loop
7. Recon committee
8. Orchestrator
9. Artifact and run logging
10. Docker Compose wiring ✅
11. Tests and demo run

## CLI Interface

```
./athena --instructions <path> --config <path>
```

Both flags are required — no defaults. Missing either is a hard error.

- `--instructions` — free-form text prompt consumed by the Orchestrator agent. The target
  is specified here, not in the config. The Orchestrator extracts it, validates scope, and
  can reject or request clarification before the pipeline runs.
- `--config` — YAML manifest (see below). Specifies artifacts directory, model choices,
  orchestrator agent path, and committee/specialist configs.

## Config YAML Structure

```yaml
artifacts_dir: ./artifacts
max_agent_iterations: 8

model:
  default: claude-haiku-4-5

orchestrator:
  model: claude-sonnet-4-6
  config: ./agents/orchestrator.yml

committees:
  recon:
    model: claude-haiku-4-5         # committee-level default
    leader:
      config: ./agents/recon_leader.yml
      model: claude-sonnet-4-6      # leader override
    specialists:
      - config: ./agents/network_scout.yml
      - config: ./agents/ssh_expert.yml
      - config: ./agents/rest_expert.yml
      - config: ./agents/apache_expert.yml
        model: claude-sonnet-4-6    # per-specialist override
```

Model resolution order (no silent defaults — hard error if unresolvable):
1. Per-specialist `model` override
2. Committee `model` default
3. Global `model.default`

Secrets (`ANTHROPIC_API_KEY` etc.) live in `.env` only — never in the YAML.

## 1. Project Scaffold

Start with the smallest runnable Python app.

Files to add:

- `pyproject.toml`
- `src/athena/__init__.py`
- `src/athena/main.py`
- `src/athena/config.py`
- `tests/`

Purpose:

- establish the Python package layout
- configure dependencies
- configure `ruff`, `black`, and the test runner
- create one entrypoint the runner container can execute

No agent behavior yet.

## 2. Authorized Target VM

Create the local target VM or VM-like container.

Purpose:

- provide a fixed, deterministic target for Recon to inspect
- avoid any external target
- make demo behavior repeatable
- expose enough signal and noise for a convincing multi-observation recon artifact

Shape:

- Ubuntu container on the docker-compose network
- Apache2 on port 80, intentionally misconfigured to serve content from `/home/admin/`
- SSH on port 22, banner only (no auth attempted)
- `credentials.json` in `/home/admin/` with fake but plausible content
- no real vulnerabilities; the misconfiguration is deliberate and fully contained

Services:

- `22/tcp` OpenSSH — banner only
- `80/tcp` Apache2 — misconfigured to expose `/home/admin/` via HTTP

Apache misconfigurations to include (all intentional for the demo):

- directory listing enabled — Recon will observe it, Planning will flag it
- `/server-status` enabled — classic Apache mod_status exposure
- `robots.txt` with a `Disallow: /home/` entry — inadvertently reveals the path
- `Server:` header left at default — exposes Apache version

The retrieval target is `http://target/home/admin/credentials.json`. Apache serves it openly
because of the misconfiguration; Retrieval uses a plain HTTP GET — no exploit, no bypass.

For Phase 1, Recon only observes what services voluntarily expose through normal client behavior.

## 3. Shared Schemas

Define the pipeline backbone.

Likely module:

- `src/athena/schemas.py`

Core schemas:

- `Classification` — enum
- `Category` — enum
- `Specialist` — expert identity (id + title)
- `Comment` — authored observation note (author_id + text)
- `RawFinding` — specialist output: command, output, and a brief technical note; no classification
- `Observation` — Leader-authored: classified, categorised, commented finding derived from RawFindings
- `ReconArtifact` — full Recon committee output, written by the Recon Leader
- `OrchestratorApproval` — emitted when Orchestrator accepts the instructions and is ready to run
- `OrchestratorRejection` — emitted when Orchestrator refuses the instructions
- later: `PlanningArtifact`
- later: `RetrievalArtifact`
- later: `ReportArtifact`

For Phase 1, implement all of the above except the later artifacts.

`RawFinding` fields:

- `id` — short hex, for cross-referencing in Leader comments
- `specialist_id` — `Specialist.id` of the expert who produced it
- `command` — tool invoked
- `command_output` — raw result, unmodified
- `notes` — specialist's brief technical note; no classification or interpretation

`OrchestratorApproval` fields:

- `run_id` — UUID, generated at approval time
- `target` — extracted by the Orchestrator from the instructions
- `notes` — Orchestrator's summary of its understanding of the engagement

`OrchestratorRejection` fields:

- `reason` — clear explanation of why the instructions were refused

`Classification` values:

- `signal_warn` — expert suspects an actionable opportunity; Planning should prioritize and
  cross-reference related observations
- `signal_info` — useful context, confirms something real, but no immediate lead implied
- `noise` — accurate but irrelevant for this target
- `unknown` — expert cannot classify without more context

`Category` values:

- `network` — port state, reachability
- `service` — service identity, version, banner
- `configuration` — server settings, headers, exposed admin paths
- `exposure` — paths or files that should not be publicly accessible
- `authentication` — auth-related observations (banners, prompts, requirements)

`Specialist` fields:

- `id` — UUID string, assigned when the specialist is instantiated for a run
- `title` — human-readable role name (e.g. `"Apache Expert"`, `"SSH Expert"`)

Specialist is a simple model for now. It is expected to grow (capabilities, model config,
tool allowlist) in later iterations.

`Comment` fields:

- `author_id` — `Specialist.id` of the specialist who wrote the comment
- `text` — the comment text

`Observation` fields:

- `id` — 8-char hex fragment, unique per observation within the run
- `specialist_id` — `Specialist.id` of the expert who produced this observation
- `command` — tool invoked or task performed
- `command_output` — raw result, unmodified
- `classification` — `Classification` value
- `category` — `Category` value
- `comments` — `list[Comment]`; for `signal_warn`, comments must reference related observation ids

`ReconArtifact` fields:

- `artifact_id` — UUID string
- `run_id`
- `committee` — always `"recon"`
- `created_at`
- `target`
- `specialists` — `list[Specialist]`; registry for resolving specialist ids in this run
- `observations` — `list[Observation]`
- `summary` — brief committee-level narrative for handoff to Planning

Every committee emits a validated pydantic artifact.

## 4. Tool Layer

Implement deterministic tools.

Likely module:

- `src/athena/tools.py`

Phase 1 tools:

- `http_get(url)`
- `check_port(host, port)`
- `http_head(url)`
- `tls_probe(host, port)`
- `ssh_banner(host, port)`
- `tcp_banner(host, port)`
- `nmap_scan(host)`
- `extract_links(html, base_url)`

Tool constraints:

- only configured local docker-compose hostnames or authorized target VM addresses
- bounded timeouts
- response size limit
- no arbitrary external access
- no path traversal normalization tricks
- no payload probes
- no exploit or vulnerability checks
- no brute forcing
- no fuzzing
- clear typed result objects

The LLM does not call raw network libraries. It can only request scoped tools.

`nmap` is allowed only behind a deterministic wrapper. The Recon committee must never construct arbitrary `nmap` commands. The port scope is hardcoded inside the wrapper (common ports); the LLM cannot influence which ports are scanned.

Approved `nmap` behavior:

- TCP connect scan only
- hardcoded bounded common-port range (internal to the wrapper, not caller-supplied)
- configured local target only
- light service/version detection only
- hard timeout
- machine-readable output parsed into a normalized result

Forbidden `nmap` behavior:

- NSE scripts, including default scripts and vulnerability scripts
- OS fingerprinting
- UDP scans
- decoy, spoofing, or firewall-evasion flags
- aggressive timing
- full-range scans
- caller-supplied port lists
- brute-force, exploit, or vulnerability checks

## 5. Model Backend

Isolate model access.

Likely module:

- `src/athena/model_backend.py`

Interface:

- `ModelBackend`
- `complete(messages, tools?)`

Implementation:

- one concrete backend for the configured provider
- a fake backend for tests

Rules:

- no direct SDK calls outside this module
- API key from the environment only
- never log the API key
- keep the provider swappable

## 6. Agent Loop

Build the core primitive.

Likely module:

- `src/athena/agent_loop.py`

Responsibilities:

- receive system prompt, input, allowed tools, and model backend
- ask the model for the next step
- execute only allowed tool calls
- append tool results
- stop when the model emits a final artifact
- validate the final artifact
- enforce a max iteration cap

This should stay small and readable, roughly 40-60 lines if possible.

Do not use a generic agent framework.

## 7. Recon Committee

Build the first actual committee.

Likely module:

- `src/athena/committees/recon.py`

The Recon committee has a Leader and four specialist roles. The Leader is an LLM agent
that coordinates specialists, receives their raw findings, classifies everything, and
writes the final `ReconArtifact`. Specialists only probe and report.

**Recon Leader**

- Receives the `OrchestratorApproval`
- Summons specialists reactively via `summon_specialist(name) -> list[RawFinding]`
- After all relevant specialists have reported, classifies every finding and writes the
  `ReconArtifact` (full `Observation` list + summary narrative)
- Has its own agent loop, its own model (default: `claude-sonnet-4-6`), and its own
  `Specialist` identity in the artifact

**Specialists** (each is a separate agent loop with scoped tools; returns `list[RawFinding]`)

1. **Network Scout** — always summoned first. Runs `nmap_scan` and `check_port`; reports
   which ports are open. No interpretation — just discovery.

2. **SSH Expert** — summoned only if port 22 is open. Runs `ssh_banner`; reports the
   banner and version string verbatim. Brief technical note only.

3. **REST Expert** — summoned only if port 80 or 443 is open. Runs `http_get`,
   `http_head`, `extract_links`. Probes a fixed path list: `/`, `/robots.txt`,
   `/server-status`, `/.well-known/`, `/admin`, `/docs`, `/api`. Reports response codes,
   headers, and body excerpts.

4. **Apache Expert** — summoned only if REST Expert's findings include `Apache` in a
   `Server:` header. Probes Apache-specific paths: directory listing behaviour, UserDir
   exposure (`/~admin/`, `/files/`, `/home/`), `/server-info`. Reports what it finds,
   no classification.

**Artifact writing**

After all summoned specialists have reported, the Leader:
- Receives the full set of `RawFinding` lists
- Assigns `Classification` and `Category` to each finding
- Cross-references related findings in `Comment` text (citing `RawFinding.id`)
- Writes a `list[Observation]` and a summary narrative
- Emits the `ReconArtifact`

Goal: ~15–25 raw findings across all specialists. Leader produces ~15–25 `Observation`
objects. Most classified as `noise` or `signal_info`; a handful as `signal_warn` pointing
toward the misconfigured Apache `/files/` path.

Do not build Planning, Retrieval, or Reporting code yet.

## 8. Orchestrator

The Orchestrator is an LLM-powered agent, not just deterministic sequencing code.
It runs in two phases.

Likely module:

- `src/athena/orchestrator.py`

**Phase 1 — Clarification loop (interactive)**

The Orchestrator reads `instructions.txt` and enters an interactive loop with the user.
It has two tools available in this phase:

- `ask_user(question: str) -> str` — prints to stdout, reads a response from stdin
- `reject_run(reason: str)` — prints the rejection reason and exits cleanly

The loop continues until the Orchestrator either:
- emits an `OrchestratorApproval` artifact (extracts target, summarises understanding)
- calls `reject_run` (instructions are out of scope or cannot be safely accommodated)

The Orchestrator may ask for clarification, request minor tweaks to the instructions, or
confirm scope. It must not start the pipeline until it has a clear, approved engagement.

**Phase 2 — Pipeline execution (deterministic)**

Once an `OrchestratorApproval` is emitted, deterministic Python takes over:

```text
approval received
  -> write approval artifact
  -> log lifecycle: run started
  -> summon Recon committee (passes target from approval)
  -> wait for ReconArtifact
  -> validate artifact
  -> write artifact
  -> log lifecycle: recon complete
  -> finish run (Phase 1 ends here)
```

Later phases extend the sequence, but Phase 1 should not scaffold them yet.

The orchestrator owns:

- run id (from OrchestratorApproval)
- artifact directory
- lifecycle logs
- committee order
- fail-fast behavior

## 9. Artifact And Run Logging

Persist outputs.

Likely module:

- `src/athena/artifacts.py`

Outputs:

- `artifacts/<run_id>/run.log`
- `artifacts/<run_id>/recon.json`

Lifecycle log should show:

```text
run started
recon committee summoned
recon committee working
recon artifact emitted
recon committee spun down
run completed
```

This makes the demo legible.

## 10. Docker Compose

Make it runnable locally.

Likely files:

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`

Services:

- `runner`
- `target`

Network:

- shared local compose network only

Volumes:

- `./artifacts:/app/artifacts`

Run command:

```bash
docker-compose up
```

## 11. Tests

Add verification.

Initial tests:

- schemas validate valid artifacts
- schemas reject malformed artifacts
- tool layer blocks non-local targets
- tool layer enforces size and time limits
- fake model can drive the Recon loop
- orchestrator writes the artifact and lifecycle log

No live external network tests.

## First Slice To Code

For the first implementation pass, keep the scope to:

1. Python scaffold
2. authorized target VM
3. schemas
4. deterministic tools
5. fake model backend
6. agent loop
7. Recon committee
8. orchestrator
9. docker-compose

Do not build Planning, Retrieval, or Reporting yet. That keeps the project compliant with the one-committee-at-a-time rule.
