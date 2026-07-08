# PLAN.md — Athena Build History

All build phases are complete. This document records what was built and in what order.
For current architecture see `ATHENA_README.md` and `AGENTS.md`.

---

## Build Order

1. ✅ Project scaffold
2. ✅ Authorized target container
3. ✅ Shared schemas
4. ✅ Tool layer
5. ✅ Model backend
6. ✅ Agent loop
7. ✅ Recon committee
8. ✅ Orchestrator
9. ✅ Artifact and run logging
10. ✅ Docker Compose wiring
11. ✅ Planning committee
12. ✅ Retrieval committee
13. ✅ Reporting committee
14. ✅ Foundation-Sec integration (Modal / vLLM)
15. ✅ Tests and demo run

---

## CLI Interface

```
athena --instructions <path> --config <path>
```

Both flags are required. Missing either is a hard error.

- `--instructions` — free-form text prompt consumed by the Orchestrator. The target is
  specified here. The Orchestrator extracts it, validates scope, and can reject or request
  clarification before the pipeline runs.
- `--config` — YAML manifest specifying artifact dir, model choices, orchestrator agent
  path, and committee/specialist configs.

---

## Config YAML structure

```yaml
artifacts_dir: ./artifacts
max_agent_iterations: 20

model:
  default: claude-haiku-4-5
  provider: anthropic
  ollama_base_url: https://<modal-endpoint>.modal.run

orchestrator:
  model: claude-sonnet-4-6
  config: ./agents/orchestrator.yml

committees:
  recon:
    model: claude-haiku-4-5
    leader:
      config: ./agents/recon/leader.yml
      model: claude-sonnet-4-6
    specialists:
      - config: ./agents/recon/network_operator.yml
      - config: ./agents/recon/service_operator.yml
      - config: ./agents/recon/web_operator.yml
      - config: ./agents/recon/threat_analyst.yml
        provider: ollama
        model: foundation-sec-8b
  # planning, retrieval, reporting follow same pattern
```

Model resolution order (hard error if unresolvable):
1. Per-specialist override
2. Committee default
3. Global default

---

## Recon committee — final architecture

The original design had a single leader summoning four specialists
(network_scout, ssh_expert, rest_expert, apache_expert) reactively via `summon_specialist`.

The implemented architecture is a four-phase Python-driven flow:

| Phase | Agent | Mechanism |
|-------|-------|-----------|
| 1 | network_operator, service_operator, web_operator (Claude) | Python iterates `_DEFAULT_TASKS`, calls `_run_operator()` directly |
| 2 | threat_analyst (Foundation-Sec-8B) | Single `backend.complete()` call — no tools, bulleted markdown output |
| 3 | leader (Claude Sonnet) | Agent loop — may `summon_operator` for analyst-recommended follow-up |
| 4 | leader | Emits `ReconArtifact` JSON |

This design emerged from empirical testing: Foundation-Sec's tool calling capability
was permanently degraded by its security fine-tuning. Using it as a pure-reasoning
CTI analyst (no tools, bulleted markdown) and routing all tool execution through Claude
preserves its security domain knowledge while eliminating the broken tool-calling path.

See `projects/FOUNDATION_MODELS_PLAN.md` for the full evaluation.

---

## Target container

Ubuntu container on the docker-compose network with intentional misconfigurations
that make the demo meaningful without being a real vulnerability:

- Apache 2.x on port 80
- Directory listing enabled on `/files/`
- `credentials.json` in `/files/` with fake but structurally realistic content
- `/server-status` enabled without auth restriction
- `robots.txt` with `Disallow: /files/` (advertises the sensitive path)
- Default `Server:` header (exposes Apache version)
- SSH on port 22 (banner only; no auth attempted by any agent)

The retrieval target is the credentials file. Retrieval uses a plain HTTP GET and a
Postgres connection with the credentials found — no exploitation, no bypass.

---

## Artifact chain

```
OrchestratorApproval  →  ReconArtifact  →  PlanArtifact  →  RetrievalArtifact  →  ReportArtifact
```

Each artifact references the prior one by ID. The full chain is written to
`artifacts/<run_id>/` alongside `run.log`.
