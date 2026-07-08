# Recon → Planning → Retrieval — Design Proposal

This document captures design decisions from a post-run analysis session. It is intended as a handoff to an implementing Claude Code session. Read the current `src/athena/committees/planning.py`, `src/athena/committees/retrieval.py`, and `src/athena/schemas.py` alongside this before touching any code.

---

## Problem statement

Planning currently produces a **flat list of `PlannedAction` objects** with narrative `description` fields. Retrieval receives this list and loosely interprets it. The connection is probabilistic — whether a specialist executes a given action depends on Claude's in-context reasoning, not a structured handoff. This caused:

- Critical actions planned across both runs but never executed (SSH auth check, credential reuse test)
- Organic discoveries appearing in one run and vanishing in the next (`pg_read_file`, `usesuper` check)
- No signal to Retrieval about what success looks like, what to do if a step fails, or when to improvise

The fix has two parts: a richer Planning output format (intent tree), and a configurable execution mode for Retrieval (creativity float).

---

## Core design: the intent tree

### Key principle

**Planning owns what to discover. Retrieval owns how to discover it.**

Planning generates a tree of **intent nodes** — lightweight descriptions of what the specialist should achieve at each step, with edges that model success/failure branching. Planning does not write full commands. Retrieval reads each node's intent and determines the correct command, query, or tool call to fulfill it.

This separation means:
- Planning can generate large trees cheaply (nodes are strings + IDs, not command syntax)
- Retrieval has creative authority over execution — it adapts to what it finds on the target
- `command_hint` is optional — Planning (or Foundation-Sec, see below) may suggest a starting point, but Retrieval is not bound to it

### Node format

```json
{
  "id": "N04",
  "intent": "confirm SSH password authentication is enabled on port 22",
  "tool_hint": "ssh_exec",
  "command_hint": "ssh-audit target -p 22",
  "on_success": ["N05", "N06"],
  "on_failure": ["N07"]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Short string, unique within the plan. Python assigns these, same as current action IDs. |
| `intent` | yes | One sentence: what should be discovered or confirmed at this node. No command syntax. |
| `tool_hint` | no | Tool category — `ssh_exec`, `postgres_query`, `http_get`, `http_head`. Narrows search space without prescribing syntax. |
| `command_hint` | no | Optional starting suggestion. Fed from Foundation-Sec output or planning specialist reasoning. Retrieval may ignore it. |
| `on_success` | yes | List of child node IDs to pursue if this node yields a positive result. Empty list = leaf. |
| `on_failure` | yes | List of fallback node IDs to pursue if this node fails or is blocked. Empty list = dead end, backtrack. |

### Example subtree — SSH vector

```
[N01] enumerate SSH service fingerprint and version
       ├─ success → [N02] confirm password authentication is enabled
       │                   ├─ yes → [N03] test db_admin credential reuse via SSH
       │                   │              ├─ success → [N04] enumerate host filesystem
       │                   │              │                   ├─ [N05] read /etc/hosts for internal topology
       │                   │              │                   ├─ [N06] search for private keys and credentials
       │                   │              │                   └─ [N07] enumerate running containers and processes
       │                   │              └─ failure  → [N08] test mk_mon_x9y8z7w6v5u4 credential via SSH
       │                   └─ no  → [N09] read authorized_keys via pg_read_file (postgres superuser path)
       │                                  └─ success → [N10] attempt key-based SSH authentication
       └─ failure → [N11] probe port 22 reachability from pgdatabase via pg_read_file /proc/net/tcp
```

The tree grows large across all vectors (SSH + web + postgres). A full engagement plan may have 40–60 nodes. Because each node is just an intent string and some edge IDs, Planning can generate this reliably even at scale.

---

## Creativity float

A `creativity: float` value (0.0–1.0) on `PlanArtifact` controls how Retrieval traverses the tree.

| Value | Retrieval behaviour |
|-------|---------------------|
| `0.0` | Walk one path per root. Pick the single most obvious command per node. Stop at the first dead end; do not explore siblings. Fully deterministic. |
| `0.5` | Follow the primary branch. If a node partially succeeds, explore one sibling branch. Stay within the tree. |
| `1.0` | Explore all promising branches. Generate child nodes for unexpected findings not in the tree. Treat the tree as a starting suggestion, not a constraint. |

At `1.0`, Retrieval can **extend the tree** — if it discovers something Planning didn't anticipate, it follows the thread and logs it as an unlabelled branch. This is the "in the field chaos" layer: structured enough to be repeatable, open enough to capture organic discoveries like `pg_read_file`.

The creativity value should be exposed as a top-level config in `athena.yml` under `retrieval:` so it can be set per engagement.

---

## Priority entry points

`PlanArtifact` replaces `actions: list[PlannedAction]` with a node map and three priority-tiered entry point lists:

```python
class PlanArtifact(BaseModel):
    ...
    nodes: dict[str, AttackNode]       # full tree, keyed by node ID
    critical_roots: list[str]          # node IDs — must be executed every run
    high_roots: list[str]              # node IDs — executed if critical roots complete
    optional_roots: list[str]          # node IDs — explored only at creativity >= 0.5
    creativity: float                  # 0.0–1.0
    summary: str
```

Retrieval exhausts `critical_roots` first, then descends into `high_roots`, then `optional_roots` based on creativity level. This maps directly to how a real operator thinks: "these three things must happen; explore further if you have time and it's going well."

---

## Schema changes required

### New: `AttackNode`

```python
class AttackNode(BaseModel):
    id: str                        # assigned by Python, not LLM
    intent: str                    # what to discover/confirm — no command syntax
    tool_hint: str | None          # optional tool category
    command_hint: str | None       # optional starting suggestion
    on_success: list[str]          # child node IDs
    on_failure: list[str]          # fallback node IDs
```

### Updated: `PlanArtifact`

Replace `actions: list[PlannedAction]` with the node map and entry point lists shown above. Keep `summary: str` and `recon_artifact_id: str` unchanged.

### Deprecate: `PlannedAction`

`PlannedAction` and `ActionPriority` can be removed once the new schema is in place. Priority is now expressed structurally (which root list a node appears in) rather than as a field on each action.

### `RetrievedFinding.action_id`

Currently references `PlannedAction.id`. Update to reference `AttackNode.id`. Semantics unchanged — a finding records which node it was executing when discovered.

---

## Foundation-Sec integration

Foundation-Sec's `## Recommended Follow-up` section contains operator-scoped bash blocks. These are currently treated as a format violation and suppressed. They should instead be parsed and routed into `command_hint` fields on the relevant nodes.

The output in Run 2 included:

**Web Operator nodes** → `command_hint`: `cat /var/www/html/files/credentials.json`, `ls -l /var/www/html/files/`  
**Network Operator nodes** → `command_hint`: `iptables -L OUTPUT -v`, `netstat -an | grep ESTABLISHED`  
**All Operators** → `command_hint`: `journalctl -u apache2 --since "1 hour ago"`, `sudo lynis audit system`

The `lynis` suggestion is particularly valuable — a professional hardening scanner that no other pipeline agent would independently generate.

Implementation path: after parsing the Foundation-Sec output in `recon.py`, extract fenced code blocks keyed by their operator header (`Web Operator:`, `Network Operator:`, `All Operators:`), and pass them to the planning committee as `suggested_commands` alongside the `ThreatAnalysis`. The planning specialists can then assign them as `command_hint` values on the appropriate nodes.

---

## Planning committee changes

The planning specialists (network_planner, web_planner) currently output a flat JSON array of action objects. They need to output **subtrees** — a list of root node IDs and a flat map of all nodes in their subtree. The leader merges subtrees and assigns nodes to `critical_roots`, `high_roots`, or `optional_roots` based on priority.

Planning specialist output format:

```json
{
  "roots": ["N01", "N11"],
  "nodes": {
    "N01": {
      "intent": "enumerate SSH service fingerprint and version",
      "tool_hint": "ssh_exec",
      "command_hint": "ssh-audit target -p 22",
      "on_success": ["N02"],
      "on_failure": ["N11"]
    },
    ...
  }
}
```

The leader merges all specialist subtrees into one node map and assigns root nodes to priority tiers.

Node IDs are assigned by Python before or after LLM generation to avoid hallucinated or colliding IDs — same pattern as current `PlannedAction.id` assignment via `new_short_id()`.

---

## Retrieval committee changes

The retrieval leader currently summons specialists and tells them: "Execute the actions in your domain." With the intent tree, the leader instead:

1. Reads `critical_roots` and resolves their node IDs from the node map
2. Summons the appropriate specialist(s) for each root, passing the node and its subtree
3. Receives findings back, determines which branch was taken (success/failure), and follows the indicated child nodes
4. Repeats until all reachable nodes are exhausted or the creativity budget is spent

The specialist receives **a single node + its subtree** (not the full plan) — it executes the intent, returns findings, and signals success/failure. Python (or the leader) walks the edge to the next node.

Whether the tree walk is Python-driven (deterministic) or leader-driven (LLM decides next node) is an open design question. Python-driven is more reliable; leader-driven allows the leader to apply judgment about which branch to follow when multiple success children exist.

---

## Open questions for the implementing session

1. **Tree walk owner**: should Python walk the `on_success`/`on_failure` edges deterministically, or should the retrieval leader read the full node map and decide traversal order? Python is more reliable; leader has judgment for multi-child branches.

2. **Node ID assignment**: assign IDs before sending to LLM (pass a schema with pre-populated IDs) or assign after (parse LLM output and re-key)? Current pattern assigns after.

3. **Foundation-Sec command extraction**: parse in `recon.py` before Planning runs, or pass raw `ThreatAnalysis.summary` to planners and let them extract? Parsing in Python is more reliable.

4. **Backwards compatibility**: `RetrievedFinding.action_id` references a node ID — no schema break, just a rename of what it points to. Tests referencing `PlannedAction` will need updating.

5. **creativity default**: suggest `0.5` as a sensible default — follows primary branches, explores one sibling on partial success, stays within the tree.
