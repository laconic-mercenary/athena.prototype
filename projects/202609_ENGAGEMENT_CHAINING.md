# 2026-09 Engagement Chaining, Transitions & Lessons-Learned

Design exploration for the highest-value capability the Engagements model still lacks:
**transitioning from one engagement into the next** — with or without operator intervention —
where the follow-on inherits the prior engagement's artifacts and carries a **lessons-learned**
memory so mistakes are not repeated. Engagements should be able to *iterate* (same committees,
refined) or *pivot* (a different ensemble with different committees). Companion to
[[202609_ARTIFACT_ZEROTRUST.md]] (they intersect at key access — see EN-X) and
[[202609_DEFICIENCIES.md]].

Status legend: **ACCEPTED** (known, fine for now) · **OPEN** (needs decision) · **FIXED** ·
**VERIFY** (needs a live check).

Design IDs: **EN0–EN7**. EN0 (durable engagement records) is the prerequisite; the rest build on it.

---

## Current state — engagements are islands

An engagement is one workflow run traversing the ensemble committee graph from `entry` to a
terminal committee, then done:

- **Single, isolated run.** [runner.py:165-189](../src/athena/server/runner.py#L165-L189):
  `start_engagement()` checks `is_busy()` (one active at a time), mints a fresh `run_id`, and
  builds an `EngagementContext` from scratch. Nothing carries over from any prior run.
- **In-memory only.** `_active` ([runner.py:58](../src/athena/server/runner.py#L58)) is a plain
  dict. A server restart erases every engagement record — there is no durable engagement history.
- **Within-run iteration already exists.** [workflow.py:245-266](../src/athena/harness/workflow.py#L245-L266)
  implements `iterate` / `retry` back-edges **between committees** inside one engagement, and
  refines the next committee's objective via `objective.append(note)`
  ([workflow.py:233](../src/athena/harness/workflow.py#L233), [:258](../src/athena/harness/workflow.py#L258)).
- **One ensemble, resolved once.** [runner.py:547-548](../src/athena/server/runner.py#L547-L548):
  the ensemble path is a single env var (`ENS_PATH`) read at start. No selection, no registry.
- **The plan is seeded from nothing but the operator message.** The orchestrator briefs from
  `capability.md` + the operator's instructions ([runner.py:301-306](../src/athena/server/runner.py#L301-L306)).
  No prior artifacts, no accumulated knowledge feed in.

**The insight:** the machinery to refine-and-retry with carried objectives already exists at the
committee level. Chaining is that same pattern **escalated one level** to the engagement graph,
plus two new things the harness has never had: a durable engagement record and a cross-engagement
memory.

---

## The model — an engagement graph over the committee graph

```
  Engagement A (ensemble: recon)                Engagement B (ensemble: exploit)
  ┌──────────────────────────┐   transition     ┌──────────────────────────┐
  │ recon → planning → …      │ ───────────────▶ │ exploit → lateral → …     │
  │ artifacts/A/*.enc         │  inherit A.recon │ seeds briefs from A       │
  │ lessons_A                 │  + lessons_A     │ produces lessons_B (⊇ A)  │
  └──────────────────────────┘                  └──────────────────────────┘
        iterate (same ensemble, new priors + lessons) ⟲     pivot (different ensemble) ⟶
```

Two transition modes, very different cost:

- **Iterate** — same ensemble/committees, re-run with the parent's artifacts as priors plus
  accumulated lessons. Cheap: reuses existing brief-refinement machinery across an engagement
  boundary. Use: re-attempt after a failed pass, run the same playbook against the next box.
- **Pivot** — transition into a *different* ensemble (different committees). Expensive: requires
  multi-ensemble selection the harness doesn't have yet. Use: recon-ensemble → exploit-ensemble →
  reporting-ensemble; or red-team → remediation-verification / purple-team.

---

## Directions

### EN0 — Durable engagement records · OPEN (prerequisite)
A chain cannot survive a restart while `_active` is in-memory. **Direction:** persist an
engagement record to disk — `engagements/<id>/meta.json` holding `{ id, parent_id, ensemble,
mode, status, started, ended, lessons_ref, inherited_from }`. `_active` becomes a cache over the
durable index. This is the one hard dependency for everything below — the lineage graph, lessons,
and inheritance all need engagements to *exist* beyond process lifetime.

### EN1 — Engagement lineage · OPEN
**Direction:** add `parent_engagement_id` (and `mode`) to the start path. An engagement may be
spawned as a **child** that links to its parent. `start_engagement()` grows optional
`parent_id` / `ensemble` / `inherit` parameters; the lineage is recorded in EN0's meta. Chains
are trees (a parent can fan out into several follow-ons), read from the durable index.

### EN2 — Artifact inheritance / seeding · OPEN
**Direction:** a child mounts selected parent artifacts **read-only** as seed context. Extend the
orchestrator's `read_artifact_fn` ([runner.py:276-281](../src/athena/server/runner.py#L276-L281))
and the `consumes` resolution so a committee/brief can reference `parent:recon`. Inherited
artifacts are provenance-tagged (never overwritten, never silently re-run). The child's briefing
seeds `CommitteeBrief.objective` from parent output instead of starting cold. **Crosses the
encryption boundary — see EN-X.**

### EN3 — Lessons-learned store (the anti-repeat memory) · OPEN
The centerpiece. A structured retro artifact produced at engagement close and fed into the next
engagement's briefing so the orchestrator and planners don't re-propose known dead-ends.

**Direction:** a `LessonsLearned` schema, roughly:
```python
class Attempt(BaseModel):
    technique: str            # what was tried (MITRE id where applicable)
    outcome: str              # "worked" | "failed" | "partial"
    cost: str                 # rough time/step spend
    why: str                  # why it failed / what the blocker was

class LessonsLearned(BaseModel):
    engagement_id: str
    parent_id: str = ""
    attempts: list[Attempt] = []
    worked: list[str] = []        # reinforce next time
    avoid: list[str] = []         # dead-ends — do NOT re-propose
    recommendations: list[str] = []  # forward guidance for the follow-on
    notes: str = ""
```
Produced by a lightweight retro element (or the reporting committee) at engagement end. On
transition it is injected into the child orchestrator's briefing context. This is the
**cross-engagement analog of `objective.append(note)`** already in the workflow — the same
"carry a refinement forward" pattern, escalated from committee to engagement. Lessons **compound
down a lineage** (child's `avoid` ⊇ parent's), so a chain gets monotonically smarter. This is
retrieval-into-context, not model training.

### EN4 — Transition trigger: operator vs autonomous · OPEN
Two ways a follow-on starts:

- **Operator-initiated.** At the terminal gate, the operator picks "start follow-on" with a
  target ensemble + inheritance selection. Reuses the existing gate UI surface.
- **Autonomous.** The orchestrator, at engagement end, may *propose* or *auto-start* a follow-on
  (exploit succeeded → spawn lateral; recon done → spawn exploit). This needs a **new terminal
  decision** alongside advance/retry/iterate: `transition(to_ensemble, mode, inherit=[…])`,
  mirroring the existing `GateDecision` model in
  [orchestrator.py](../src/athena/harness/orchestrator.py) / consumed at
  [workflow.py:199-266](../src/athena/harness/workflow.py#L199-L266).

**Direction:** add the `transition` decision at the engagement boundary. An **autonomous** pivot
is always gated by an operator_approval **unless** explicitly pre-authorized in scope — a
red-team follow-on must never silently exceed the Rules of Engagement (this ties to the
mandatory scope gate in [[202609_REDTEAM_GENERICIZATION.md]]).

### EN5 — Sequential chain execution · OPEN
**Direction:** the single-worker model is a feature here, not a limitation. When A completes and
transitions, B starts automatically on the same worker — a chain is **sequential**, not
concurrent, which fits [runner.py:57](../src/athena/server/runner.py#L57)'s one-at-a-time
executor cleanly. `is_busy()` becomes "is the *chain* active." No multi-run UI/operator model is
required (that remains the concurrency blocker noted in the runner TODO), because a chain is
still one live engagement at a time.

### EN6 — Ensemble registry (pivot enabler) · OPEN
Pivot mode needs multiple ensembles available and selectable per engagement; today `ENS_PATH` is
one path resolved once. **Direction:** an ensemble registry (a directory of ensembles + an index)
and per-engagement ensemble selection at start / at the `transition` decision. Iterate mode does
**not** need this (it reuses the parent's ensemble), so EN6 can lag behind EN1–EN5 — ship
iterate-only chaining first, add pivot when the registry lands.

### EN7 — Reporting consumes the chain · OPEN
**Direction:** a final report should narrate the whole lineage, not one hop. Reporting consumes
the lineage index (EN0) + each engagement's artifacts + `LessonsLearned`, producing a chain-level
engagement report. Small delta once EN0/EN3 exist.

---

## Cross-link — where this meets zero-trust · EN-X
EN2 inheritance collides with per-engagement encryption in [[202609_ARTIFACT_ZEROTRUST.md]]:
parent artifacts are sealed under the parent's DEK (ZT3), so a child cannot read them by default.
**Direction:** at transition, re-wrap the parent's DEK to the child as an **operator-gated,
audited key delegation** — inheritance becomes explicit key grant, not implicit file access. This
gives the operator a clean point to *deny* propagation of sensitive loot into a follow-on (e.g.
pass recon forward but not recovered credentials). Chaining and zero-trust are co-designed here;
neither should land EN2/ZT3 without the other's grant model in view.

---

## Phasing

- **P0 — EN0.** Durable engagement records. Unblocks the lineage graph, lessons, inheritance.
- **P1 — EN1 + EN2 + EN3, iterate-only.** Lineage, artifact seeding, lessons-learned, same
  ensemble. This is the demo-able core: run an engagement, then re-run it smarter.
- **P2 — EN4.** The `transition` decision + operator/autonomous trigger with the scope gate.
- **P3 — EN6 + pivot.** Ensemble registry, cross-ensemble transitions.
- **P4 — EN7.** Chain-level reporting.

---

## Open questions
- **Lessons format: structured vs freeform?** Recommending structured (`LessonsLearned` above) so
  the child orchestrator can be *told* "avoid X" rather than re-reading prose — confirm the schema
  is worth the rigidity.
- **Artifact roots: shared vs per-engagement + links?** Recommend per-engagement roots with
  inheritance pointers (cleaner, and it matches the crypto-shred story in ZT3).
- **Autonomous transition + scope** — what, if anything, may a chain pivot into *without* an
  operator gate? Default: nothing. Needs an explicit pre-authorization mechanism in the plan.
- **Lessons provenance/trust** — a child inheriting a parent's `avoid` list trusts the parent's
  retro. Bad lessons poison the chain. Do we let the operator edit/prune lessons at transition?
- **Chain depth / termination** — an autonomous chain needs a budget (max hops / global step
  budget across the chain) so it can't run away. Extends
  [workflow.py:44](../src/athena/harness/workflow.py#L44)'s `GLOBAL_STEP_BUDGET` to chain scope.

## Notes
- EN0 is the unlock, exactly as ZT0 is for the sibling doc: without a durable record, none of the
  interesting behaviour survives a restart. Do it first.
- The cheapest high-value slice is **P1 iterate-only** — it needs no ensemble registry and no
  `transition` decision, just lineage + seeding + lessons on the existing single ensemble. That is
  the thing to build first if we want a fast demo of "the second run is smarter than the first."
- Pivot (EN6) is where the cost is. Keep it out of the critical path — iterate delivers most of
  the "lessons compound" value on its own.
