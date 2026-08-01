# Scan Committee Playbook

## Element inventory
| Element | What it does | Specialists | Task card |
|---------|--------------|-------------|-----------|
| `count_regular_files` | Count files whose name does NOT start with '.' | `Regular File Counter` | elements/count_regular_files/task.md |
| `count_hidden_files` | Count files whose name starts with '.' | `Hidden File Counter` | elements/count_hidden_files/task.md |

## Standard sequencing
This committee is a **single Step** with two Tasks — one for each element — submitted in parallel.
You receive two labeled result sections (`[count_regular_files]` and `[count_hidden_files]`).
Synthesise them, then `finish` with the ScanOutput. There is no second Step in the normal case.

## Confirmation before finishing
Once counting is complete, call `ask_operator` **once** with a one-line summary of the counts
(e.g. "Found 12 regular + 3 hidden .py files, 4 .md, 2 .sh across 21 files total. Ready to seal
the ScanOutput?"). Then wait.

If the operator asks a side question (factual, conversational, or off-topic), answer it with a
single `reply_operator` call and **stop there** — do not append another confirmation request to
the same reply. The operator knows you are waiting; let them come back to you.

Only call `finish` when the operator explicitly approves (e.g. "yes", "proceed", "go ahead").

## When to adapt
- **Directory unreadable, or zero totals across all extensions in both specialists** — do not
  re-run blindly. `ask_operator` to confirm the path or the extension list.
- **Large tree** — a single walk still suffices; do not split by directory.

## What the leader does not do
The leader does not walk the filesystem or open file contents — that is each element's specialist's
job via its dedicated skill. The leader only assembles counts from both elements into the ScanOutput.
