# Foundation-Sec Integration — Evaluation and Outcome

## Goal

Incorporate an open-source security-specialist model into the Athena pipeline to bring
domain knowledge about CVEs, port services, Apache configuration, and credential exposure
patterns without prompting Claude to reason about security context from scratch.

---

## Model evaluated: Foundation-Sec-8B-Reasoning

| Property | Value |
|---|---|
| Model ID | `fdtn-ai/Foundation-Sec-8B-Reasoning` |
| Base | Meta Llama 3.1 8B |
| Context | 32,768 tokens |
| Security tuning | CTI-MCQA 0.691, CTI-RCM 0.753, CTI-VSP 0.856 |
| Reasoning | Extended chain-of-thought (`<think>…</think>` blocks) |
| Tool calling | **Broken** — see findings below |

---

## Infrastructure — Modal + vLLM

Local CPU inference (~1 tok/s) was too slow for interactive use. The model is deployed on
[Modal](https://modal.com) with an A10G GPU (~80–120 tok/s):

```
infra/modal/modal_serve.py  →  modal deploy  →  https://<workspace>--athena-foundation-sec-serve.modal.run
```

Key deployment config:
- Base image: `nvidia/cuda:12.1.1-devel-ubuntu22.04` (devel required for vLLM JIT)
- GPU: A10G, `memory=32768` (prevents OOM during safetensors load from NFS volume)
- `--safetensors-load-strategy prefetch`
- `--max-model-len 32768`, `--dtype bfloat16`
- API key auth via `athena-vllm-key` Modal secret

### Setup (one time)

```bash
# 1. Install Modal and authenticate
pip install modal
modal setup

# 2. Create the API key secret
modal secret create athena-vllm-key VLLM_API_KEY=<your-token>

# 3. Download Foundation-Sec weights into the Modal volume (~16 GB)
modal run infra/modal/modal_serve.py::download_model

# 4. Deploy
modal deploy infra/modal/modal_serve.py
```

Set `OLLAMA_API_KEY=<your-token>` in `.env`. `OllamaBackend` sends it as
`Authorization: Bearer` on every request.

---

## Tool calling evaluation

Tool calling was the primary risk: Llama 3.1 8B (the base) supports function calling,
but security fine-tuning may alter this behaviour.

### Tests performed

| Test | Result |
|---|---|
| llama-cpp-python + `llama-3` chat format | Hallucinated tool calls (wrong format) |
| llama-cpp-python + `llama-3-groq-tool-use` format | Not supported |
| llama-cpp-python + `chatml-function-calling` format | Hallucinated tool calls |
| vLLM + `llama3_json` tool parser + `get_time` tool | Model refused (non-security topic) |
| vLLM + `llama3_json` tool parser + `nmap_scan` tool | Wrote 1,000-token essay; never called tool |

**Conclusion: tool calling is permanently broken in this model.** The security fine-tuning
rewrote the output distribution in a way that is incompatible with function-calling format.
This cannot be fixed through prompt engineering or parser selection.

---

## Outcome — Revised architecture

Rather than discarding Foundation-Sec, the recon committee was redesigned to use it for
what it does well: **pure analytical reasoning over pre-gathered findings**.

### Two-class model architecture

| Class | Model | Role | Tools |
|-------|-------|------|-------|
| Operators | Claude (Haiku / Sonnet) | Tool execution, data collection | nmap_scan, http_get, ssh_banner, etc. |
| Analyst | Foundation-Sec-8B | CTI reasoning over findings | None |
| Leader | Claude Sonnet | Synthesis, artifact emission | summon_operator (Phase 3 only) |

### Recon committee phases

```
Phase 1 — Python runs network_operator, service_operator, web_operator (Claude)
           _DEFAULT_TASKS maps each operator to a default task; _run_operator() called directly
           Findings collected into findings_by_operator dict

Phase 2 — Python calls threat_analyst (Foundation-Sec) with a single backend.complete()
           Input: formatted operator findings
           Output: bulleted markdown threat assessment (stored as ThreatAnalysis.summary)

Phase 3 — Leader (Claude Sonnet) enters agent loop
           Initial message: Phase 1 findings + Phase 2 threat assessment
           May summon_operator for analyst-recommended follow-up
           Emits ReconArtifact JSON
```

### Foundation-Sec output format

Foundation-Sec is prompted for four headed sections in plain bullets — no JSON, no code
blocks:

```
## CVE Candidates
- CVE-XXXX-XXXXX — [service/version] — [why it applies]

## Risk Indicators
- [misconfiguration or exposure]

## Recommended Follow-up
- [operator_name]: [specific action]

## Assessment
[2–3 sentence summary]
```

The Python layer stores the full response as `ThreatAnalysis(summary=raw_text)` and
embeds it verbatim in the leader's initial context. Claude reads the markdown naturally.
No JSON parsing, no `extract_json()`, no try/except.

### Why this works

- Foundation-Sec's security domain knowledge is preserved — it correctly identifies CVEs,
  misconfigurations, and risk indicators from raw scan output
- The structured markdown format is reliable — the model follows section headers even when
  it cannot follow JSON schemas
- Claude handles all tool execution and structured artifact emission, where it is reliable
- The leader receives richer context (analyst report + operator findings) than the old
  single-leader-with-summon approach

---

## Config

`athena.yml` — only the threat_analyst uses `provider: ollama`:

```yaml
model:
  default: claude-haiku-4-5
  provider: anthropic
  ollama_base_url: https://<workspace>--athena-foundation-sec-serve.modal.run

committees:
  recon:
    specialists:
      - config: ./agents/recon/network_operator.yml   # Claude (default)
      - config: ./agents/recon/service_operator.yml   # Claude (default)
      - config: ./agents/recon/web_operator.yml       # Claude (default)
      - config: ./agents/recon/threat_analyst.yml
        provider: ollama
        model: foundation-sec-8b                      # Foundation-Sec via Modal
```

---

## What was not pursued

- **Qwen2.5 hybrid** — not needed once the two-class architecture resolved the tool
  calling problem cleanly
- **Fine-tuning** — out of scope; published weights used as-is
- **Foundation-Sec for Retrieval** — original plan included Retrieval; abandoned when
  tool calling was confirmed broken. Claude handles Retrieval with no loss of quality.
- **Local Ollama** — CPU too slow (~1 tok/s for 8B); Modal A10G is the only viable host
