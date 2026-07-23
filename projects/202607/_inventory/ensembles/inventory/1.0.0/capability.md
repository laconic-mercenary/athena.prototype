# Capability — inventory

## What this ensemble does
Counts files by extension under a target directory and produces a short, readable inventory
report. **Read-only:** it walks the directory and counts file extensions; it never opens file
contents, moves, or modifies anything.

## What to establish in briefing
- **directory** — the absolute path to inventory.
- **extensions** — the list of extensions to count, each with the dot (e.g. `.py`, `.md`, `.txt`).
  If the operator does not give a list, ask.

## Committees

### scan
- **Input:** the directory + extension list (from the engagement brief).
- **Output:** `ScanOutput` — per-extension counts, total files matched, the resolved directory,
  and any paths skipped (unreadable).
- **Adequate when:** the directory was walked and a count is present for every requested extension.
- **Retry if:** the directory was unreadable, or no extensions were counted at all.

### report
- **Input:** the `ScanOutput`.
- **Output:** `ReportOutput` — a one-paragraph summary and a markdown table of extension → count,
  with the total.
- **Adequate when:** the table lists every counted extension and the total matches the ScanOutput.

## Constraints
- Read-only filesystem access — counting only, never reading file contents, never writing.
- The directory must resolve inside the allowed roots (harness-enforced by the `count_extensions`
  skill).

## Ask the operator if
- The directory is missing, not a directory, or ambiguous.
- No extensions were provided.
