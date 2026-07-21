# Element: Findings Analysis

Synthesise technical findings from ReconOutput, PlanOutput, and RetrievalOutput
into a clear, evidence-based narrative section for the final report.

## What this element produces

A JSON object with a title ("Technical Findings") and a prose content field
(300-600 words). Covers: what was discovered in recon, what was retrieved and
confirmed, the chain of discovery, and concrete data (hostnames, ports, paths,
file contents, query results). No risk ratings or recommendations.

## Skills available

None — pure reasoning element.

## Adequacy criterion

Output is adequate when the content field references specific observation IDs,
finding notes, or tool outputs from the upstream artifacts. Generic prose not
tied to specific evidence is not adequate.
