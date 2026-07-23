# Report Committee Playbook

## Element inventory
| Element | What it does | Task card |
|---------|--------------|-----------|
| `summarize` | Turn the ScanOutput counts into a readable markdown summary + table | elements/summarize/task.md |

## Standard sequencing
A **single Step**: one `summarize` Task over the ScanOutput. When it returns, `finish` with the
ReportOutput.

## When to adapt
- **Zero files counted** — still produce the report; state plainly that nothing matched.

## What the leader does not do
The leader does not re-count or touch the filesystem. It formats the counts the Scan committee
already produced.
