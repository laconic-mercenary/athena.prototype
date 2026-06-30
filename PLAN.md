# PLAN.md - Athena Build Plan

## Build Order

1. Project scaffold
2. Authorized target VM
3. Shared schemas
4. Tool layer
5. Model backend
6. Agent loop
7. Recon committee
8. Orchestrator
9. Artifact and run logging
10. Docker Compose wiring
11. Tests and demo run

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
- `Observation` — one finding from one expert role
- `ReconArtifact` — full committee output
- later: `PlanningArtifact`
- later: `RetrievalArtifact`
- later: `ReportArtifact`

For Phase 1, only implement `Classification`, `Category`, `Observation`, and `ReconArtifact`.

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

The Recon committee is composed of four expert roles. Each role is a separate agent loop
with its own system prompt and scoped tool subset. Roles run sequentially; later roles
depend on earlier ones. The committee aggregates all observations into one `ReconArtifact`.

Roles and dependency order:

1. **Network Scout** — runs `nmap_scan` and `check_port`; establishes which ports are open.
   All other roles depend on its output.

2. **SSH Expert** — runs `ssh_banner` on port 22 if Scout found it open. Logs the banner,
   version string, and any pre-auth information. Expected to produce mostly `noise` and
   `signal_info` observations in this scenario.

3. **REST Expert** — runs `http_get`, `http_head`, and `extract_links` on discovered HTTP
   ports. Probes a hardcoded list of common paths: `/`, `/robots.txt`, `/server-status`,
   `/.well-known/`, `/admin`, `/docs`, `/api`. Logs response codes, headers, body excerpts,
   and extracted links. Expected to surface `signal_warn` observations (directory listing,
   `robots.txt` disallow entries, `server-status` exposure).

4. **Apache Expert** — runs only if REST Expert found `Apache` in a `Server:` response
   header. Probes Apache-specific paths and interprets directory listing behavior, UserDir
   exposure, and header configuration. Expected to produce the highest-value `signal_warn`
   observations pointing toward the exposed credentials path.

Each role produces a `list[Observation]`. The committee merges the lists, orders by role,
and emits a single `ReconArtifact` with a summary narrative.

Goal: ~15–25 observations total across all roles. Most are `noise` or `signal_info`;
a handful are `signal_warn` pointing Planning toward the misconfigured Apache path.

In v1, all four roles are hardcoded in the committee. Dynamic role addition (e.g. spawning
the Apache Expert only after discovering Apache) is the intended future behavior but is not
built yet.

Do not build Planning, Retrieval, or Reporting code yet.

## 8. Orchestrator

Wire deterministic sequencing.

Likely module:

- `src/athena/orchestrator.py`

Phase 1 behavior:

```text
start run
  -> summon Recon committee
  -> wait for ReconArtifact
  -> validate artifact
  -> write artifact
  -> log lifecycle
  -> finish run
```

Later phases extend the sequence, but Phase 1 should not scaffold them yet.

The orchestrator owns:

- run id
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
