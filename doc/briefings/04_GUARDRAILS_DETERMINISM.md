# 04 — Guardrails & Determinism

*Framed for the inevitable question: "what stops this from going rogue like the ChatGPT / Anthropic
autonomous-hacking write-ups?" Short answer: **the operator is in the loop by design, the agents are
boxed to least privilege, and everything is observed and typed.***

## Rogue-prevention guardrails

### The operator is in the loop by design
- **`operator_approval` gate** between planning and exploit — **no exploit traffic reaches the
  target** until the operator reviews the plan and clicks Accept. Mandatory, declared in the plan.
- **`ask_operator` moments** — the exploit leader must pause, with the discovery evidence, **before**:
  privilege escalation, reaching an internal datastore, and reading credentials / sensitive data.
- **In-loop tool gate** — the operator can *arm* element / step / tool gates. With the tool gate
  armed, **every side-effecting skill (`touches_target`) pauses for approve/deny** before it goes on
  the wire.
- **KILL SWITCH** — one click aborts the engagement and unwinds the harness threads, at any point.
- **Collaboration co-approval** — a gate can require a **second human's** email/link approval before
  advancing (two-person rule).

### The agents are boxed (least privilege)
- **Per-element toolset** — a specialist can call **only** the skills its element declares; nothing
  else exists in its tool list (the OSINT analyst has `http_get` and nothing more).
- **Tool-call budgets** — default **1** executed skill call per specialist (per-element override),
  bounded attempts, bounded iterations. A model can't loop or spam tools.
- **`side_effect` tiers** — every skill is tagged `reads_local` vs `touches_target`, so the harness
  and operator always know which calls actually touch the target.
- **Non-interactive RCE** — exploitation is **one auditable command per HTTP request** with output
  returned inline. No reverse shell, no persistent foothold, every action logged.
- **Network segmentation** — Redis lives on a separate `db-net` reachable **only from the target**;
  the harness can never reach it directly, and the crown-jewel credential stays root-only behind
  privesc.
- **(Planned) operator tool enable/disable** — the operator can switch specific tools off at
  briefing; disabled skills are pruned from every agent's toolset for the whole run.

### Everything is observed
- Every model message, tool call + result, gate, and finding is **streamed live (SSE)** to the
  console — real-time auditability, not a post-hoc log.
- **Typed artifacts + KILL SWITCH** — a bad committee output is caught by schema validation, or the
  run is halted by the operator.

## What helps determinism
- **Typed output contracts (Pydantic)** — each committee must emit a valid schema at `finish()`;
  malformed output is re-prompted, never passed downstream. *This is the main rail.*
- **Capability doc `briefing_required`** — constrains what the orchestrator collects and how it
  briefs, so the plan shape is stable across runs.
- **Adequacy criteria + retry/iterate** — each committee has explicit "adequate when / retry if"
  rules; the workflow re-runs an inadequate committee (bounded counts).
- **Compare + `select_result`** — model diversity reduces single-model variance; the leader
  adjudicates on substance, and a MITRE specialist **standardizes** technique mapping.
- **Structured leader prompts** — a defined standard Step sequence, an output JSON template, and
  explicit guards (e.g. *"the public domain is not the target"*) reduce drift.
- **Low temperatures / bounded tokens** on workers; **deterministic skills** (nmap, http, github,
  the dark-web / OS-fingerprint stubs) return structured data, not vibes.
- **Guards against known failure modes** — recon can't hand a CDN edge to exploit as the target;
  planners defer MITRE mapping to a specialist; budgets prevent tool-spam loops.

## Honest caveats (for Q&A — don't oversell)
- Models still **author prose** (summaries, rationale). Determinism is at the **structure and
  control** level, not word-for-word.
- The **operator gates and schema validation are real and load-bearing.** A few conveniences (the
  tool-disable panel, some in-loop gates) are wired for the demo and being hardened.
- The target is **intentionally vulnerable and sandboxed** — the point is to show the *control
  surface*, not that the model can pop an arbitrary host.
