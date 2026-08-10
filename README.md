<div align="center">

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 90" width="340" height="90">
  <!-- owl icon -->
  <g transform="translate(18, 8) scale(1.15)">
    <path d="M12 22 Q22 7 33 18" stroke="#3b82f6" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <path d="M31 18 Q42 7 52 22" stroke="#3b82f6" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <circle cx="22.5" cy="24" r="11" stroke="#3b82f6" stroke-width="3" fill="none"/>
    <circle cx="41.5" cy="24" r="11" stroke="#3b82f6" stroke-width="3" fill="none"/>
    <circle cx="25.5" cy="23" r="3.3" fill="#3b82f6"/>
    <circle cx="38.5" cy="23" r="3.3" fill="#3b82f6"/>
    <path d="M29 30 L35 30 L32 37 Z" stroke="#3b82f6" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    <path d="M12.5 30 C10 46 20 58 32 58 C44 58 54 46 51.5 30" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" fill="none"/>
    <path d="M28 57 l-1.5 4 M32 58.5 l0 4 M36 57 l1.5 4" stroke="#3b82f6" stroke-width="2.8" stroke-linecap="round" fill="none"/>
  </g>
  <!-- wordmark -->
  <text x="102" y="56"
    font-family="'SF Mono', 'Fira Code', 'Cascadia Code', monospace"
    font-size="38"
    font-weight="700"
    letter-spacing="10"
    fill="#3b82f6">ATHENA</text>
  <!-- tagline -->
  <text x="103" y="76"
    font-family="'SF Mono', 'Fira Code', 'Cascadia Code', monospace"
    font-size="10"
    letter-spacing="3"
    fill="#64748b">ORCHESTRATION HARNESS</text>
</svg>

</div>

---

Athena is an **operator-supervised AI orchestration harness**. It runs a declarative
pipeline of specialist AI committees through a task — each phase doing real work,
emitting a validated artifact, and pausing at a gate for the operator to review before
the next phase begins.

What Athena runs is defined by an **ensemble**: a directory containing a manifest, leader
prompts, specialist prompts, skill implementations, and output schemas. Swapping the
ensemble directory changes the entire workflow — no code changes required. The harness
is domain-agnostic; the ensemble is where the use case lives.

The bundled ensemble (`tests/ensembles/redteamv1`) runs an authorized red team
engagement: OSINT discovery → network recon → MITRE-mapped attack planning → exploitation
→ formal report.

---

## Concepts

**Ensemble** — the engagement definition. A directory containing a manifest, committee
configs, specialist prompts, skill implementations, and output schemas. Swapping the
ensemble directory changes the entire workflow.

**Committee** — one phase of the engagement. A leader LLM drives the committee through
a just-in-time planning loop, dispatching work to specialists and synthesising their
outputs into a structured artifact.

**Element** — a named unit of work within a committee. Elements in the same step run
in parallel. Each element has one or more specialists and a declared set of tools.

**Specialist** — the LLM that performs the element's task. When an element has multiple
specialists, they run in compare mode: each produces a variant, and the leader selects
the most credible result.

**Gate** — the operator checkpoint between committees. The operator reads the committee's
output digest, optionally opens the full artifact, approves to advance, or triggers a
retry/iterate. No committee advances without operator sign-off.

**Artifact** — the structured output a committee emits. Artifacts are validated against a
Pydantic schema, stored to disk, and consumed verbatim by downstream committees.

---

## Architecture

```
Operator (React UI) ──── HTTP / SSE ────► FastAPI server  (server.py)
                                                │
                                                │  ENSEMBLE_PATH env var
                                                ▼
                                       Ensemble Harness
                                                │
                              ┌─────────────────┼──────────────────┐
                              ▼                 ▼                  ▼
                       Committee A        Committee B          Committee C
                       (N elements)       (N elements)         (N elements)
                              │                                    │
                              └────────── operator gate ───────────┘
```

The server loads the ensemble at startup. When the operator starts an engagement, the
harness runs the workflow graph from the entry committee forward, pausing at each gate
for operator approval. The UI shows live committee progress via SSE and surfaces each
gate as an interactive dialog.

### Bring your own model

Each specialist and leader in an ensemble declares its own model. The harness has no
opinion on which models you use — swap them in the specialist YAML without touching
any code.

The only requirement is **tool use support**. Specialists that call skills need a model
capable of tool calling. Reasoning-only specialists (no tools, pure text output) work
with any model.

The harness supports two providers out of the box:

- **`provider: anthropic`** — any Claude model via the Anthropic API
- **`provider: ollama`** — any model behind an OpenAI-compatible `/v1/chat/completions`
  endpoint (Modal vLLM, Ollama, LM Studio, etc.), set via `OLLAMA_BASE_URL`

Mix providers freely within a single ensemble. A planning committee can run three
specialists in compare mode — one Claude, one Foundation-Sec, one Kimi — and the
harness dispatches them concurrently without additional configuration.

See `doc/ENSEMBLES.md` → *Specialists* for the full `provider`, `model`, and
`temperature` field reference.

---

## Installation

**Python:**

```bash
pip install -e ".[dev]"
```

**UI:**

```bash
cd src/ui && npm install && npm run build && cd ../..
```

The built UI is served statically by the FastAPI server — no separate UI server needed.

---

## Configuration

Copy `.env.example` to `.env` and fill in values.

**Required:**

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ENSEMBLE_PATH` | Absolute or relative path to the ensemble directory |

**Optional:**

| Variable | Default | Description |
|----------|---------|-------------|
| `ORCHESTRATOR_MODEL` | `claude-sonnet-4-6` | Model for the orchestrator phase |
| `REPORT_CHAT_MODEL` | `claude-haiku-4-5-20251001` | Model for the post-engagement debrief chat |
| `OLLAMA_BASE_URL` | — | vLLM endpoint for specialists that use `provider: ollama` |
| `RESEND_API_KEY` | — | Resend API key — enables collaborator email for gate approvals |
| `COLLAB_REPLY_DOMAIN` | — | Resend reply-to domain for collaborator threads |

---

## Running the server

```bash
python server.py
```

Optional flags:

```bash
python server.py --host 0.0.0.0 --port 8000 --verbose
```

`--verbose` streams agent reasoning to stdout. Once started, the operator UI is at
`http://localhost:8000`.

---

## Running an engagement

1. Open the operator UI at `http://localhost:8000`.
2. Enter the engagement instruction in the chat pane and send it.
3. The orchestrator proposes an engagement plan — review it and approve or revise.
4. Each committee runs sequentially. Track live progress in the dashboard.
5. At each **gate**, a dialog presents the committee's output digest. Options:
   - **Accept** — advance to the next committee.
   - **Redo** — discard the output and re-run the committee from scratch (with optional
     guidance on what to change).
   - **Iterate** — keep the output and ask the committee to refine a specific aspect.
6. When the final committee completes, the engagement is done. Full artifacts are
   available under `artifacts/<run_id>/`.

### Operator collaboration

Gate approvals can require a second operator. If `RESEND_API_KEY` is configured, the
gate dialog accepts a collaborator `@alias`. The collaborator receives an email, replies
to approve or deny, and their response appears in the gate thread in real time.

---

## Ensembles

### Using the bundled ensemble

Point `ENSEMBLE_PATH` at `tests/ensembles/redteamv1` and start the server. The
orchestrator accepts a domain name as the engagement target and runs the full redteam
pipeline against it.

The redteam ensemble requires:
- `nmap` installed on the server machine
- `OLLAMA_BASE_URL` configured if the Foundation-Sec or Kimi planning variants are enabled
- Outbound internet access from the server (for OSINT skills)

### Building a new ensemble

An ensemble is a directory with this layout:

```
my-ensemble/
├── manifest.yml       # workflow graph, committee and element declarations, skills registry
├── capability.md      # orchestrator briefing + briefing_required block
├── schemas/           # Pydantic output schema per committee
├── committees/        # leader YMLs + playbook.md per committee
│   └── <committee>/
│       ├── leader.yml
│       ├── playbook.md
│       └── elements/<element>/<specialist>.yml
└── skills/            # skill tool definitions + Python implementations
    └── <skill>/
        ├── skill.yml
        └── impl.py
```

Set `ENSEMBLE_PATH` to your ensemble directory and restart the server. See
`doc/ENSEMBLES.md` for the full authoring reference.

---

## Tests

### Unit tests

```bash
pytest
```

Unit tests use `FakeBackend` — no live network or API calls required. They cover the
ensemble loader, committee runner, workflow engine, skill executor, agent loop,
collaboration, and artifact handling.

Key test files:

```bash
pytest tests/test_committee_runner.py -v   # committee runner, compare mode, element gating
pytest tests/test_orchestrator.py -v       # orchestrator: approval gate, plan extraction
pytest tests/test_agent_loop.py -v         # core agent loop mechanics and tool dispatch
pytest tests/test_collaboration.py -v      # collaborator thread and email gate flow
```

### System integration tests

Each scenario in `tests/system/` is a self-contained Docker stack with its own ensemble,
fixtures, and run scripts. System tests exercise the full server with live API calls.

| Scenario | What it validates |
|----------|-------------------|
| `fs-scan/` | Minimal ensemble: file inventory across a known directory tree |
| `redteam_easy/` | Redteam pipeline against a local Docker target, no RCE |

```bash
cd tests/system/fs-scan
./run.sh     # build → start → wait for healthy → print UI URL
./stop.sh    # tear down
```

---

## Codebase

| Path | What it contains |
|------|-----------------|
| `server.py` | Entry point — FastAPI + uvicorn; configured via env vars |
| `src/athena/server/` | Routes, SSE event bus, engagement lifecycle (`runner.py`) |
| `src/athena/harness/` | Workflow engine, committee runner, skill executor |
| `src/athena/ensemble/` | Manifest loader, typed structs (`LoadedEnsemble`, etc.) |
| `src/ui/src/` | React operator UI |
| `infra/modal/` | Modal vLLM deployments for Foundation-Sec and Kimi |

See `AGENTS.md` for contributor guidance and `doc/ENSEMBLES.md` for the ensemble
authoring reference.
