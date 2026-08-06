# Ensembles — Developer Reference

An **ensemble** is a self-contained unit of work: a manifest that declares a workflow
graph of committees, the specialists each committee summons, the skills those specialists
can call, and the Pydantic schemas that validate each committee's output. The harness
reads an ensemble at startup and drives it end-to-end; the operator watches via the UI.

The ensemble lives entirely in its own directory tree. The harness (`src/athena/`) never
needs to change to add a new committee, new specialist, or new skill — that is all done
by editing YAML and Python inside the ensemble directory.

> **Reference ensemble:** `tests/ensembles/redteamv1/`  
> **Minimal reference ensemble:** `tests/ensembles/fsscanv1/`

---

## Filesystem layout

```
tests/ensembles/<name>/
├── manifest.yml                    # required — workflow, committees, skills registry
├── capability.md                   # required — orchestrator briefing + briefing_required block
├── requirements.txt                # optional — ensemble-specific pip deps
├── schemas/
│   ├── __init__.py                 # re-exports all schema classes
│   └── <committee>_output.py       # one Pydantic model per committee
├── committees/
│   └── <committee>/
│       ├── leader.yml              # required — leader system prompt and optional model override
│       ├── playbook.md             # optional — long-form context injected into the leader brief
│       └── elements/               # specialist YAML files, one per element
│           └── <element>/
│               └── <specialist>.yml
└── skills/
    └── <skill>/
        ├── skill.yml               # tool definition shown to the LLM
        └── impl.py                 # deterministic Python implementation
```

All paths inside `manifest.yml` are relative to the ensemble root.

---

## `manifest.yml` — complete reference

```yaml
name: my-ensemble          # slug identifier for the ensemble
version: 1.0.0             # semver; shown in the UI
description: >             # one paragraph; shown in the UI and capability.md
  What this ensemble does.
capability_doc: capability.md   # relative path to the orchestrator capability doc
```

### Workflow graph

```yaml
workflow:
  entry: <first_committee>   # name of the entry-point committee node

  nodes:
    <committee_name>:
      output_schema: schemas.<ClassName>  # Python import path inside the ensemble's schemas/
      transitions:
        - to: <next_committee>            # normal advance (no condition = always available)
        - to: <same_or_other>
          condition: retry               # operator triggers: discard output, start fresh
        - to: <same_or_other>
          condition: iterate             # operator triggers: refine existing output
```

**Transitions are mutually exclusive choices** offered to the operator at the gate. There
is always at most one transition without a `condition` (the advance path). `retry` and
`iterate` edges may point to a different committee if the workflow warrants it; most
ensembles loop back to the same node.

A terminal committee has no advance transition — only `retry` and/or `iterate` edges.

### Committees

```yaml
committees:
  <committee_name>:
    leader: <committee>/leader.yml      # relative to ensemble root
    model: claude-sonnet-4-6            # default model for this committee's leader
    max_steps: 8                        # max JIT-loop iterations; harness default is 12

    consumes:
      required: [<committee_name>, ...]   # prior artifacts injected via render_full()
      optional: [<committee_name>, ...]   # injected via render_digest() when available

    elements:
      - id: <element_id>                # snake_case; unique within the ensemble
        label: Human-readable label     # shown in the UI
        max_tool_calls: 4               # optional — cap on domain-tool calls per step
        specialists:
          - <committee>/elements/<element>/<specialist>.yml
          - <committee>/elements/<element>/<specialist_b>.yml  # triggers compare mode
        skills: [skill_id_a, skill_id_b]   # skill IDs from the skills registry below
```

**`max_steps`** caps the leader's JIT planning loop (how many times it can call
`submit_step`). Low values are fine for simple committees that always finish in one step.

**`max_tool_calls`** throttles how many times the specialists within an element call
domain tools across one harness step. Useful when a specialist has a natural ceiling
(e.g. one lookup per external source).

**`consumes`** controls which prior committee artifacts are available in the leader brief:
- `required` — the artifact is injected verbatim via `render_full()`. Missing = hard error.
- `optional` — the artifact is injected via `render_digest()` when present; absent artifacts
  are silently omitted from the brief.

### Skills registry

```yaml
skills:
  - id: skill_id            # unique slug; must match what elements declare in `skills:`
    definition: skills/<skill>/skill.yml   # relative path to the tool definition
    impl: skills/<skill>/impl.py::<fn>     # Python module path :: function name
```

All skills used by any element must appear in the registry. The harness resolves them at
startup and will error if a declared skill is missing its definition or implementation.

---

## `capability.md` — orchestrator briefing

The orchestrator reads `capability.md` before proposing the `EngagementPlan` to the
operator. It serves two purposes:

1. **Tells the orchestrator what this ensemble can do** — committees, inputs, operator gates.
2. **Declares `briefing_required`** — the structured inputs the orchestrator must collect
   from the operator before the ensemble can run.

### `briefing_required` block

```markdown
## briefing_required

\`\`\`yaml
briefing_required:
  - name: <field>
    type: string | integer | boolean
    example: "example value"
    description: >
      What this field is and where to find it in the operator's message.
      Tell the orchestrator whether to extract it from context or ask explicitly.
\`\`\`
```

The orchestrator uses this block to populate the engagement plan's `objective` field. Keep
the descriptions action-oriented: tell the orchestrator _how_ to find the value ("extract
from the operator's message" vs "ask if not provided").

### Operator gate declarations

Declare every `operator_approval` gate that should appear in the `EngagementPlan`:

```markdown
## Operator gates

| After | Type | Redo available |
|-------|------|----------------|
| `planning` | operator_approval | yes (iterate) |
```

The orchestrator reads this section and includes the gates in the plan it proposes. If a
gate is not declared here, the orchestrator may not include it.

---

## Leaders

A leader is the LLM that drives a committee. It runs the JIT planning loop — deciding
which elements to submit in each step, interpreting their outputs, and eventually calling
`finish()` to emit the committee's structured output.

### `leader.yml` format

```yaml
title: My Leader
model: claude-sonnet-4-6       # optional; overrides the committee default
system: |
  System prompt. Explain the leader's role, the available loop tools, a standard
  execution plan, adequacy criteria, and the output JSON structure.
```

The leader does not declare skills — it has access to a fixed set of harness-provided
loop tools (`submit_step`, `finish`, `refuse_start`, `ask_operator`, `reply_operator`).
For compare-mode committees, it additionally receives `select_result`.

### `playbook.md`

If a `playbook.md` file exists alongside `leader.yml`, the harness injects its content
into the leader's initial brief under the heading `== Your playbook ==`. Use this for:

- Element inventory tables (what each element does, which skill it calls)
- Adequacy criteria (what "done" looks like)
- Escalation criteria (when to call `ask_operator`)
- Disambiguation notes too long to fit cleanly in the system prompt

The system prompt and the playbook are both always injected. Keep the system prompt
focused on the loop API and the standard execution plan; use the playbook for reference
material the leader may need to look up during a run.

### What the leader receives in its first message

The harness builds the leader's initial user message from these sections, joined by blank
lines:

1. **Engagement context** — `run_id`, objective, and engagement scope.
2. **Required upstream artifacts** — each required artifact rendered via `render_full()`,
   prefixed with `=== <committee_name> (required) ===`.
3. **Optional upstream artifacts** — each present optional artifact rendered via
   `render_digest()`.
4. **Prior output** (iterate only) — the committee's own previous output rendered via
   `render_full()`, with a note that this is a refinement.
5. **Playbook** — if `playbook.md` exists.
6. **Element task cards** — see below.
7. **Begin prompt** — `"Begin: submit your first Step."` (or a retry/iterate variant).

### JIT loop tools

```
submit_step(step)        — dispatch one Step; returns a dict of element_id → output
finish()                 — emit the final output JSON (validated against output_schema)
refuse_start(reason)     — abort; used when the brief has no usable input at all
ask_operator(question)   — pause and surface a question to the operator
reply_operator(message)  — answer an operator chat message and continue
```

For compare-mode committees, `select_result(variant_label, reasoning)` is also available.

---

## Elements

An element is a named unit of parallel work within a committee step. The leader briefs
each element with a task description; the harness dispatches all elements in a step
concurrently, then returns their labeled outputs to the leader.

### Single-specialist elements (standard mode)

One specialist YAML → the specialist runs, its output is returned directly.

```yaml
- id: port_scan
  label: Port Scanner
  specialists:
    - committees/recon/elements/port_scan/scanner.yml
  skills: [nmap_scan]
```

### Multi-specialist elements (compare mode)

Two or more specialist YAMLs → all run in parallel, each producing a variant output. The
harness labels them (e.g. `"Port Scanner (model-a)"`, `"Port Scanner (model-b)"`) and
presents all variants to the leader via `select_result`. The leader picks the best one and
explains why. The operator sees all variants at the gate and may override the selection.

```yaml
- id: exploit_planner
  label: Exploit Analyst
  specialists:
    - committees/planning/elements/exploit_planner/planner_a.yml    # Claude Haiku
    - committees/planning/elements/exploit_planner/planner_fs.yml   # Foundation-Sec
    - committees/planning/elements/exploit_planner/planner_kimi.yml # Kimi-K2
  skills: []
```

**When to use compare mode:** when multiple model families have meaningfully different
strengths on the task (e.g. tactical exploit planning, where domain-specific fine-tuned
models may outperform general-purpose ones). For most elements, a single specialist is
correct.

### `skills` scoping

Only skills listed on the element are available to its specialists. Listing a skill that
the specialist's prompt doesn't use is harmless but misleading. Never add a skill that
performs an action the specialist's prompt doesn't explicitly exercise.

---

## Specialists

A specialist is an LLM agent focused on one narrow task within an element. It receives
the leader's task brief and calls tools from its element's skill set.

### `specialist.yml` format

```yaml
title: Port Scanner             # human-readable; used as the variant label in compare mode
model: claude-haiku-4-5-20251001  # optional; overrides the committee default
provider: anthropic              # optional; use "ollama" for vLLM endpoints (Foundation-Sec, Kimi)
temperature: 0.3                 # optional; float 0.0–1.0; use for compare diversity
max_tokens: 4096                 # optional; increase for prose-heavy output (report writers need 8192)
system: |
  System prompt. Keep it narrow. Explain exactly what the specialist should do,
  which tool to call, and what to return. No scope beyond the task.
```

**`max_tokens` ceiling:** Haiku 4.5's hard ceiling is 8192. The harness default is 4096 —
sufficient for tool-calling specialists (one call, short output). Increase to 8192 for
any specialist writing extended prose (reports, narratives).

**`temperature`** is most useful in compare mode: give each variant a different temperature
to increase output diversity, making the comparison more informative.

**`provider: ollama`** routes to the `OLLAMA_BASE_URL` env var (a Modal vLLM endpoint or
any OpenAI-compatible API). The `model:` field must match the model name on that server.

### Writing effective specialist prompts

- State the role in the first sentence.
- Name the tool(s) to call and when to call them.
- Specify exactly what to return (format, fields, level of detail).
- Keep scope narrow — a specialist that tries to do two different things is harder to
  replace and harder to brief.
- No commentary beyond the result unless the leader needs interpretive framing.

Example of a good, narrow prompt:

```
You are a port scanner specialist. Call nmap_scan with the target, ports, and flags
from your brief. Return the result verbatim. No commentary.
```

---

## Skills

A skill is a deterministic Python function exposed to specialists as a tool. The LLM
calls it by name; the harness routes the call to the implementation, validates inputs,
and returns the result.

### `skill.yml` format

```yaml
name: http_get                  # must match the skill's `id` in manifest.yml
description: >
  One-paragraph tool description shown to the LLM. Be precise — the LLM uses this
  to decide when and how to call the tool.
side_effect: touches_target | none    # annotate honestly; "touches_target" means network I/O
parameters:
  url:
    type: string                # string | integer | boolean | object | array
    description: >
      What the LLM should pass. Be specific about format (e.g. "Full URL including scheme").
    required: false             # omit for required params (presence = required)
  headers:
    type: object
    description: Optional HTTP headers as a JSON object.
    required: false
returns: >
  What the function returns in plain language. Describe the shape of the result —
  the LLM uses this to interpret tool output.
notes: >
  Optional — constraints, safety notes, or behaviour the LLM should know
  (e.g. "read-only", "recurses into subdirectories", "extension matching is case-insensitive").
```

### `impl.py` format

```python
def my_skill(param_name: str, other_param: list | None = None, **kwargs):
    """Keep implementations short, deterministic, and side-effect-annotated."""
    # Required params arrive as positional keyword args.
    # Optional params default to None when not supplied.
    # **kwargs absorbs any extra keys the harness passes (don't rely on them).
    ...
    return {"result": ..., "count": N}  # must be JSON-serialisable
```

Raise `ValueError` to surface a tool-call error message to the specialist. The harness
catches it and returns the error string as the tool result — the specialist should handle
it gracefully (retry, escalate, or return what it has).

**Implementation rules:**
- No LLM calls inside skill impls.
- No side effects beyond what `side_effect:` declares.
- Validate inputs defensively; raise `ValueError` with a clear message on bad input.
- Return a JSON-serialisable dict or scalar. Do not return Pydantic models.
- Keep impls short and readable — they are audited for safety.

### `requirements.txt`

If skill implementations require pip packages not in the core harness (`pyproject.toml`),
list them in `requirements.txt` at the ensemble root. The harness server does not install
these automatically — the deployment environment (system-test image, prod container) is
responsible for installing them at container build time.

---

## Schemas

Each committee must have a Pydantic output schema. The harness validates the leader's
`finish()` JSON against it; validation failure is surfaced to the leader as a tool error.

### File location and naming

```
schemas/
├── __init__.py             # must re-export every schema class used in manifest.yml
└── <committee>_output.py   # one module per committee
```

`schemas/__init__.py` must explicitly re-export the classes referenced in `manifest.yml`:

```python
from .recon_output import ReconOutput
from .plan_output import PlanOutput
```

### Schema conventions

```python
from __future__ import annotations
from pydantic import BaseModel

class DiscoveredPort(BaseModel):
    port: int
    protocol: str = "tcp"
    service: str
    version: str = ""         # default to "" not None for optional string fields

class ReconOutput(BaseModel):
    target: str               # required fields come first, no default
    open_ports: list[DiscoveredPort]
    cve_candidates: list[CveCandidate] = []   # optional lists default to []
    attack_surface_summary: str
    mitre_hypotheses: list[str] = []

    def render_full(self) -> str:
        """Full-fidelity text view — injected into downstream committees' leader briefs."""
        ...

    def render_digest(self) -> str:
        """Compact summary — injected into the gate body and optional-artifact briefs."""
        ...
```

### `render_full()` and `render_digest()` contracts

Both methods are **optional** but strongly recommended for any schema whose data flows
downstream.

| Method | Used by harness for |
|--------|---------------------|
| `render_full()` | Required upstream artifacts in the leader brief; iterate brief; artifact API `?render=true` |
| `render_digest()` | Gate body shown to the operator; optional upstream artifacts in the leader brief |

**`render_full()`** should produce a complete, structured text representation of the
artifact — all fields the downstream committee might need. Structured text (labeled
sections, lists) is better than raw JSON because it consumes fewer tokens and is easier
for the leader to parse.

**`render_digest()`** should produce a compact summary — one or two lines — that tells
the operator whether the output looks adequate before they approve the gate. Include the
most decision-relevant numbers.

If neither method is defined, the harness falls back to `model_dump_json()`.

### Schema design rules

- Required fields first, optional fields with defaults second.
- Use `str = ""` not `str | None` for optional strings — downstream code is simpler.
- Use `list[X] = []` not `list[X] | None` for optional lists.
- Keep field names consistent with what the leader's system prompt tells it to emit.
  Mismatches between the prompt and the schema cause validation loops.
- Do not add `Optional[...]` fields unless the value is genuinely absent in some runs
  (not just "the leader might not fill this in").

---

## The leader JIT loop — how it works

The leader runs in a bounded loop. Each iteration is called a **step**. Steps are the
unit of parallelism: elements within one step run concurrently; their outputs are
collected and returned to the leader.

```
leader receives initial brief
  │
  └─► calls submit_step(step)
            │
            ├─► harness dispatches step.tasks in parallel (one per element)
            │         each task runs its specialist(s) + skills
            │
            └─► harness returns { element_id: output_text, ... } to leader
                      │
                      └─► leader decides next action:
                              submit_step(...)  → another step (up to max_steps)
                              finish()          → emit output JSON (validated)
                              ask_operator(...) → pause, surface question to UI
                              refuse_start(...) → abort (no usable input)
```

### Step and Task structure

A step contains one or more tasks. Each task targets one element:

```json
{
  "tasks": [
    {
      "element": "port_scan",
      "brief": "Scan 10.10.11.5, ports 1-1000, flags -sV -sC -T4."
    },
    {
      "element": "web_enum",
      "brief": "Enumerate http://10.10.11.5:5000. Check common paths."
    }
  ]
}
```

The leader controls which elements run together. Elements in one step run in parallel;
elements in separate steps run sequentially. Design the leader prompt to exploit
parallelism: tasks that don't depend on each other should be in the same step.

### `ask_operator` vs `refuse_start`

- `ask_operator(question)` — pauses the engagement; the operator answers via the UI chat;
  the leader receives the answer and continues. Use when information is missing but the
  engagement can continue once it's provided.
- `refuse_start(reason)` — terminates the committee run immediately. Use only when the
  brief is fundamentally unusable (no target at all, no scope).

---

## Artifact consumption and the upstream brief

When a committee declares `consumes`, the harness injects prior artifacts into the
leader's first message:

```yaml
consumes:
  required: [recon]    # ReconOutput.render_full() injected under "=== recon (required) ==="
  optional: [planning] # PlanOutput.render_digest() injected if present
```

The leader can also retrieve raw artifact JSON via the `read_artifact(committee)` skill
(if the ensemble includes it). Use this when a specialist needs the full structured data
rather than the text rendering.

---

## Testing an ensemble

### Unit tests

Unit tests live in `tests/` at the repo root and use `pytest`. The `FakeBackend` in
`src/athena/model_backend.py` drives all committee and orchestrator tests without live
network calls. Use it to test:

- Schema validation (does the leader's output parse correctly?)
- Skill implementation correctness (unit-test `impl.py` functions directly)
- Committee runner mechanics (`tests/test_committee_runner.py` for reference)

### System integration tests

Each scenario in `tests/system/<name>/` is a self-contained Docker stack: its own
`docker-compose.yml`, `run.sh`, `stop.sh`, ensemble, and fixtures.

The `fsscanv1` ensemble + `tests/system/fs-scan/` is the canonical minimal example:

```
tests/system/fs-scan/
├── docker-compose.yml   # athena_web service + mounted testdata volume
├── run.sh               # build → start → wait for healthy → print URL
├── stop.sh              # docker compose down
├── instructions.txt     # the engagement instruction text
└── testdata/            # read-only filesystem the ensemble scans
    └── src/             # known file tree with predictable extension counts
```

The system test validates the ensemble end-to-end against a real (though controlled)
environment. Run it by executing `run.sh` and then manually verifying the operator UI
output, or by scripting against the API after the server is healthy.

---

## Non-negotiable rules for ensemble developers

1. **No offensive or exploit code.** Skill implementations must not perform vulnerability
   exploitation, auth bypass, injection, fuzzing, or path traversal. Recon skills use
   normal handshakes and metadata reads only. If a skill would perform an offensive
   action, stop and flag it — do not build it.

2. **Skills are deterministic; LLM calls go in specialist prompts.** Skill `impl.py`
   files are pure Python — no Anthropic SDK calls, no `requests` calls to LLM APIs.

3. **Skill scoping is a security boundary.** Do not widen an element's `skills:` list
   without explicit approval. The listed skills are the only tools the specialist has
   access to.

4. **Do not modify the harness to accommodate an ensemble.** If the harness doesn't
   support a pattern you need, the ensemble design should change — not the harness.
   Surface the gap and discuss it.

5. **Keep specialist prompts narrow.** A specialist that does two different things is
   two specialists. Composability comes from element design, not from cramming logic
   into one prompt.

6. **Schema fields must match leader prompts exactly.** If the system prompt tells the
   leader to emit `"attack_surface_summary"`, the schema field must be named
   `attack_surface_summary`. Mismatches cause validation errors in prod.

7. **`render_full()` and `render_digest()` must not raise.** They are called during the
   live engagement. Return a sensible fallback string for empty/partial artifacts.
