# Red Teaming Ensemble — Capability Document

This document is read by the orchestrator. It describes what this ensemble does,
what each committee is responsible for, and how to evaluate outputs and route work.

---

## What this ensemble does

Executes a structured offensive security engagement against a single named target.
Produces a formal engagement report with classified observations, an attack plan,
retrieved evidence, and risk-rated recommendations.

Scope is network-layer and application-layer only. No physical access. No social
engineering. All operations are read-only at the database layer.

The ensemble runs four committees in sequence. The orchestrator controls advancement
between committees and may loop back to a previous committee with revised instructions
if an output is inadequate.

---

## Workflow

```
recon → planning → retrieval → reporting
```

**Entry:** `recon`  
**Terminal:** `reporting` — no retry or loop-back from this committee.

**Sequence:**

| Step | Committee | Gate after |
|------|-----------|-----------|
| 1 | recon | _(orchestrator evaluates — always implicit)_ |
| 2 | planning | `operator_approval` — operator must approve the plan before Retrieval starts |
| 3 | retrieval | _(orchestrator evaluates — always implicit)_ |
| 4 | reporting | _(terminal)_ |

**Gate behaviour:**
- The orchestrator evaluates every committee boundary — this is always implicit. At each
  boundary it calls `advance()`, `retry(note)`, or `ask_operator(question)`.
- `operator_approval` gates are the only type declared in the EngagementPlan. They add a
  mandatory human Proceed before the orchestrator can advance. Use after Planning at minimum.
  May be added after any committee via the EngagementPlan.

**Retry behaviour:** on retry, the committee re-runs with a revised brief. The previous artifact is overwritten. The orchestrator should include a `retry_note` in the revised brief explaining what was inadequate.

The orchestrator produces an `EngagementPlan` during the briefing dialogue that declares which gates to enforce and per-committee objectives, constraints, and emphasis. The harness reads this plan before the pipeline starts.

---

## Committees

### Recon

**Input:** target hostname, operator scope notes  
**Output:** `ReconOutput` — classified observations, threat analysis, summary narrative

**What it does:** Enumerates open ports and service versions (Network Scan element),
probes service-level banners and TLS configuration (Service Probe element), crawls
HTTP paths and retrieves exposed content (Web Crawl element), and performs CTI
reasoning over all operator findings using a security-specialist model (Threat Analysis
element). The leader synthesises all findings into classified observations and a summary.

**Adequate when:**
- At least 3 observations are recorded
- At least one `signal_critical` or `signal_warn` observation is present, OR the
  threat analyst has explicitly assessed no actionable risk
- The summary references specific ports, services, or paths (not generic filler)

**Loop back if:**
- Fewer than 3 observations with no threat_analysis summary — scan was likely incomplete
- All observations are classified `noise` or `unknown` without analyst justification

**Ask the operator if:**
- `signal_critical` observations are present — offer to halt before Planning and
  confirm the operator wants to proceed
- Credentials or secrets were found in HTTP-served files

---

### Planning

**Input:** `ReconOutput`  
**Output:** `PlanOutput` — prioritised action list, attack summary

**What it does:** Two planning specialists analyse the ReconOutput from their domains
(network-layer and web-layer) and suggest prioritised actions. The leader merges,
deduplicates, and orders by priority into the final plan.

**Adequate when:**
- At least one `critical` or `high` priority action is present
- `signal_critical` observations from Recon have at least one corresponding `critical`
  action in the plan
- The summary explains the primary attack vector

**Loop back if:**
- No `critical` actions despite `signal_critical` observations in ReconOutput —
  planning missed the primary finding
- Actions reference observation IDs that don't exist in the ReconOutput

**Ask the operator if:**
- Planned actions would target systems or subnets not explicitly in the declared scope
- The plan includes irreversible operations (file modification, service restart)

**Gate:** operator approval required before Retrieval starts.

---

### Retrieval

**Input:** `PlanOutput` + `ReconOutput`  
**Output:** `RetrievalOutput` — findings from executed actions, summary narrative

**What it does:** Two retrieval specialists execute planned actions in their domains.
Web Retrieval specialist executes web-layer actions using HTTP tools. Database
Specialist executes credential-based PostgreSQL queries using credentials found in
ReconOutput. The leader summarises what was actually retrieved.

**Adequate when:**
- At least one finding with non-empty `tool_output` is present
- All `critical`-priority actions from the plan have a corresponding finding
  (even if the finding is a failure/blocked result)

**Loop back if:**
- All findings have empty or error `tool_output` — specialists failed to connect;
  retry with revised credential hints if available from ReconOutput
- No `critical`-priority actions were attempted

---

### Reporting

**Input:** `ReconOutput` + `PlanOutput` + `RetrievalOutput`  
**Output:** `ReportOutput` — executive summary, risk rating, sections, recommendations

**What it does:** Findings Analyst synthesises technical findings from all upstream
artifacts into a clear narrative. Risk Assessor rates overall severity and produces
prioritised remediation recommendations. The leader combines both outputs with an
executive summary into the final report.

**Adequate when:**
- `risk_rating` is assigned
- At least two sections are present (Technical Findings + Risk Assessment minimum)
- `recommendations` list is non-empty and actionable

**This is a terminal committee.** No retry or loop-back from Reporting.

---

## Model notes

- All committee leaders and most specialists use `claude-sonnet-4-6` by default.
- The `threat_analysis` element uses `foundation-sec-8b` via Ollama (Modal/vLLM).
  This model has no tool-calling capability — it reasons over pre-gathered text only.
  Do not attempt to give it tools. It outputs structured markdown, not JSON.

---

## Engagement constraints

- All network tools validate the target hostname against an allowlist before executing.
  The LLM cannot influence which hosts are contacted.
- Port scope for nmap is hardcoded in the skill implementation.
- Database access is read-only (`default_transaction_read_only=on`).
- Database host is separately allowlisted (`pgdatabase` only).
