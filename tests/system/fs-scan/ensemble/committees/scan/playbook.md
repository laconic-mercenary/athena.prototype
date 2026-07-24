# Scan Committee Playbook

## Element inventory
| Element | What it does | Task card |
|---------|--------------|-----------|
| `count_files` | Walk the directory read-only and tally files per requested extension | elements/count_files/task.md |

## Standard sequencing
This committee is a **single Step**: one `count_files` Task over the directory with the requested
extensions. When its output returns, `finish` with the ScanOutput. There is no second Step in the
normal case.

## When to adapt
- **Directory unreadable, or a zero total across all extensions** — do not re-run blindly.
  `ask_operator` to confirm the path or the extension list.
- **Large tree** — a single walk still suffices; do not split it.

## What the leader does not do
The leader does not walk the filesystem or open file contents — that is the element's job via the
`count_extensions` skill. The leader only assembles the counts into the ScanOutput.
