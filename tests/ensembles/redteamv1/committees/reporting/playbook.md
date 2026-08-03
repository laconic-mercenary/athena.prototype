# Reporting Committee Playbook

## Element inventory

| Element | Mode | Skills |
|---------|------|--------|
| `report_writer` | Single specialist | none (reasoning only) |

## Standard sequence

This committee is a **single Step** followed by `finish()`.

**Optional pre-step:** if the ExploitOutput digest is not sufficient context, call
`read_artifact("recon")` or `read_artifact("planning")` before submitting the step.
The writer's brief should include everything they need to produce a complete report.

**Step 1:** Submit one task for `report_writer` with a brief that includes:
- Full ExploitOutput contents (shell obtained, user, techniques, data harvested, commands)
- Relevant recon context if available (open ports, CVEs)
- Attack plan context if available (which vectors were attempted)

**finish:** Synthesise the ReportOutput from the writer's markdown output.

## Risk rating

| Outcome | Rating |
|---------|--------|
| Root access obtained and/or sensitive data exfiltrated | Critical |
| Unprivileged shell obtained, no escalation or data access | High |
| Partial access (information disclosure only) | Medium |
| No access obtained | Low |

## Adequacy

The ReportOutput is adequate when:
- executive_summary covers what happened in plain language
- findings_markdown has at least one finding with a technique ID
- recommendations_markdown addresses the primary exploit path
- techniques_confirmed lists the confirmed ATT&CK IDs with names
