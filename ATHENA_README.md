# Athena

A proof-of-concept **agent committee pipeline**: you give one high-level instruction, an
orchestrator summons specialist committees that each do a phase of work, produce an
artifact, hand it to the next, and spin down. The demo theme is a simplified, authorized
red team engagement (recon → planning → retrieval → reporting) — the point is the
**orchestration paradigm**, not red teaming.

> **Status:** all four committees implemented and running end-to-end.

---

## What this is (and isn't)

- **Is:** a demonstration that committees can be summoned, do real work, hand off artifacts,
  and spin down — coordinated by an orchestrator, with a traceable artifact chain.
- **Isn't:** an offensive tool. No exploitation of any kind. Agents use services as
  configured; Recon performs bounded local service inventory only; Retrieval is a plain
  HTTP client and a Postgres client using credentials the target server openly exposes.

---

## Architecture

```
Human instruction
      │
      ▼
 Orchestrator (Claude Sonnet)
      │  approves run, extracts target
      ▼
 Recon Committee
      │  Phase 1: network_operator → service_operator → web_operator  (Claude, parallel tasks)
      │  Phase 2: threat_analyst (Foundation-Sec-8B, pure reasoning, no tools)
      │  Phase 3: leader (Claude Sonnet) — optional operator follow-up
      │  Phase 4: leader emits ReconArtifact
      ▼
 Planning Committee (Claude)
      │  leader + network_planner + web_planner → PlanArtifact
      ▼
 Retrieval Committee (Claude)
      │  leader + web_retriever + db_specialist → RetrievalArtifact
      ▼
 Reporting Committee (Claude)
      │  leader + findings_analyst + risk_assessor → ReportArtifact
      ▼
 artifacts/<run_id>/{approval,recon,plan,retrieval,report}.json + run.log
```

### Model allocation

| Role | Model | Provider |
|------|-------|----------|
| Orchestrator | claude-sonnet-4-6 | Anthropic |
| Recon operators (×3) | claude-haiku-4-5 | Anthropic |
| Recon threat analyst | Foundation-Sec-8B-Reasoning | Modal (vLLM, A10G) |
| Recon leader | claude-sonnet-4-6 | Anthropic |
| Planning, Retrieval, Reporting | claude-haiku-4-5 / sonnet-4-6 | Anthropic |

Foundation-Sec is used exclusively as a pure-reasoning CTI analyst — it receives operator
findings and returns a bulleted threat assessment. It does not call tools. All tool
calling is handled by Claude. See `projects/FOUNDATION_MODELS_PLAN.md` for full context.

---

## Quick start

```bash
# 1. Copy and fill in credentials
cp .env.example .env
# Add ANTHROPIC_API_KEY and OLLAMA_API_KEY (Modal vLLM token)

# 2. Bring up the target container
docker-compose up -d target

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Run the pipeline
athena --instructions instructions.txt --config athena.yml
```

Artifacts land in `./artifacts/<run_id>/`. The run log shows each committee lifecycle:
`summoned → working → artifact emitted → spun down`.

---

## Key files

| File | Purpose |
|------|---------|
| `athena.yml` | Pipeline config — models, committee specs, artifact dir |
| `.env` | Secrets (ANTHROPIC_API_KEY, OLLAMA_API_KEY) — never commit |
| `src/athena/` | Core Python package |
| `src/athena/committees/` | One module per committee |
| `agents/` | Agent YAML prompts, organised by committee |
| `infra/modal/modal_serve.py` | Modal deployment for Foundation-Sec vLLM server |
| `docker/target/` | Authorized target container (Apache + SSH + intentional misconfigs) |
| `artifacts/` | Run outputs — JSON artifacts + run.log per run |
| `projects/FOUNDATION_MODELS_PLAN.md` | Foundation-Sec evaluation and outcome |
| `AGENTS.md` | Standing rules for coding agents |

---

## Running tests

```bash
pytest
```

93 tests covering schemas, tools, model backend, agent loop, and all four committees.

---

## The one rule that matters most

No offensive or exploit code, ever. Agents use services as configured. If a feature would
drift toward offensive capability, stop and flag it. See `AGENTS.md`.
