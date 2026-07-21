# Element: Web Retrieval

Execute all web-layer planned actions against the target. Retrieve exposed files,
follow credential chains, enumerate identified paths.

## What this element produces

A JSON array of RetrievedFinding objects. Each finding records a tool call,
the action_id it was executing, the tool input and output, and a concise note
of what the finding means for the engagement.

## Skills available

- `http_get(url)` — HTTP GET; returns status, headers, body.
- `http_head(url)` — HTTP HEAD; returns status and headers only.
- `extract_links(html, base_url)` — parses HTML and returns all unique links.

## Adequacy criterion

Output is adequate when all `web_enumeration`, `exposure`, and `configuration_audit`
category actions from the PlanOutput have at least one corresponding finding entry.
