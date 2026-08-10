# Planning Committee Playbook

## Element inventory

| Element | Mode | Specialists | Skills |
|---------|------|-------------|--------|
| `exploit_planner` | Compare (3 variants) | planner_a (Claude Haiku), planner_fs (Foundation-Sec), planner_kimi (Kimi-K3) | none |

## Standard sequence

This committee is a **single Step** followed by `select_result`.

**Step 1:** Submit one task for `exploit_planner`. All three specialists run in parallel
and return independent attack plans. The result section shows three labelled variants.

**select_result:** Pick the plan most likely to succeed against this specific target.
Provide a rationale referencing specific elements of the chosen plan (CVE, technique,
realistic success criteria).

**finish:** Synthesise the PlanOutput from the selected plan.

## Adequacy

The PlanOutput is adequate when:
- At least one attack vector has a specific exploit path (not just "try SQL injection").
- The primary vector is supported by evidence from the ReconOutput.
- The MITRE chain contains at least two technique IDs.

## Escalation criteria (ask_operator)

- The recon output contains no CVE candidates and no web paths — ask whether to proceed
  with a speculative plan or gather more recon first.
- All three planners produce vague or contradictory plans — ask for operator guidance
  on which vector to prioritise.
