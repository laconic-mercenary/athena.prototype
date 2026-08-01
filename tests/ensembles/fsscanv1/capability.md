# Capability — inventory

## What this ensemble does
Counts files by extension under a target directory, **split by visibility (regular vs hidden)**,
and produces a short, readable inventory report. **Read-only:** it walks the directory and counts
file extensions; it never opens file contents, moves, or modifies anything.

Hidden files are those whose filename starts with a dot (e.g. `.env`, `.gitignore`, `.debug.py`).
The scan runs two elements in parallel — `count_regular_files` for non-hidden files and
`count_hidden_files` for hidden files — and reports both counts separately alongside a combined total.

## briefing_required
Inputs the orchestrator collects during briefing (a guide — fill from the operator's message
where possible; ask only for what is missing):

```yaml
briefing_required:
  - name: directory
    type: string
    example: /home/user/projects
    description: Absolute path to walk (must resolve inside the allowed roots)
  - name: extensions
    type: array
    example: [".py", ".md", ".txt"]
    description: Extensions to count, each including the dot
```

## Committees

### scan
- **Input:** the directory + extension list (from the engagement brief).
- **Output:** `ScanOutput` — per-extension counts (regular + hidden combined), total files matched,
  hidden file count, regular file count, the resolved directory, and any paths skipped.
- **Adequate when:** both elements completed their walk and a count is present for every
  requested extension.
- **Retry if:** the directory was unreadable, or both elements returned zero across all extensions.

### report
- **Consumes:** `scan` (required — the full `ScanOutput`).
- **Output:** `ReportOutput` — a one-paragraph summary and a markdown table of extension → count,
  with the total and a note on the regular/hidden split.
- **Adequate when:** the table lists every counted extension and the total matches the ScanOutput.

## Constraints
- Read-only filesystem access — counting only, never reading file contents, never writing.
- The directory must resolve inside the allowed roots (harness-enforced by the element skills).

## Ask the operator if
Gate-time escalation only. (Briefing-time inputs are covered by `briefing_required` above — they
are resolved before the run starts, not at a gate.)

- The scan returned **zero files across all requested extensions** despite a valid, readable
  directory — confirm the directory and extension list before finalising an empty inventory.
- The `ScanOutput` is malformed, or the resolved directory differs materially from what was requested.
