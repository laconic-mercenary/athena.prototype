# Codex Audit — August 2026

## Purpose and scope

This is a read-only architecture and implementation audit of the Athena prototype as it
existed on 2026-08-12 at commit `e5dff16` (`feat/redteam_upgrade`). It is intended to be a
concrete engineering handoff: confirmed defects are separated from accepted prototype
limitations, documentation drift, and future hardening work.

The review covered:

- the ensemble loader and in-memory ensemble types;
- model backends and the common agent loop;
- orchestrator briefing and gate evaluation;
- committee execution, specialist dispatch, tool scoping, and artifact validation;
- workflow traversal, retry/iterate behavior, and operator gates;
- FastAPI lifecycle, routes, SSE bridging, cancellation, and collaboration seams;
- React state, SSE handling, plan review, gate dialogs, and specialist toggles;
- the benign `fsscanv1` ensemble end to end;
- the red-team ensemble at the manifest, capability, and control-plane level only;
- unit-test inventory and current project design documents.

No `.env` content was inspected. No offensive skill implementation was exercised or audited.
No runtime model or network calls were made.

## Executive assessment

Athena has a strong prototype core. Its best design decision is the separation between fuzzy
model output and deterministic control: manifests define the available workflow, skills are
granted per element or specialist, the common agent loop bounds model iterations, domain-tool
calls have execution budgets, committee output is validated with Pydantic, and operator gates
are implemented with explicit thread rendezvous rather than prompt convention.

The largest risks are at the boundaries around that core. Two confirmed defects can produce an
incorrect or unsafe control outcome: a committee refusal is eventually recorded as a completed
engagement, and an invalid in-loop gate action can release a tool gate as approved. Several
other controls are described but not enforced (`global_step_budget`, retry/iterate caps, and
`instances`). The loader and plan validator also accept graph and plan shapes that can fail late
or silently omit intended gates.

The application remains appropriate for a single-operator local prototype. It is not ready to
be exposed on a network or used as a durable system of record: APIs are unauthenticated, the
server binds to all interfaces by default, artifacts are plaintext, active engagement state is
in memory, SSE has no event replay, and cancellation is cooperative with a window in which a
new engagement may start before the prior worker has actually stopped.

## Severity scale

| Severity | Meaning |
|---|---|
| Critical | Can bypass a safety boundary or produce a materially unsafe action with ordinary API use. |
| High | Can corrupt engagement outcome, violate a declared invariant, or make a run materially unreliable. |
| Medium | Important correctness, operability, or maintainability gap; generally needs a specific trigger. |
| Low | Documentation drift, misleading configuration, or bounded prototype debt. |

## Findings summary

| ID | Severity | Finding | Classification |
|---|---|---|---|
| C1 | Critical | In-loop gate actions are not validated by gate kind; unknown tool-gate actions approve execution | Confirmed defect |
| H1 | High | Committee refusal emits rejection but the runner then records the engagement as completed | Confirmed defect |
| H2 | High | The advertised global step budget and retry/iterate limits are not enforced | Confirmed defect |
| H3 | High | Plan validation does not bind committee names or gates to the loaded ensemble | Confirmed defect |
| H4 | High | Aborting immediately frees capacity before the prior worker has necessarily stopped | Confirmed concurrency defect |
| H5 | High | Artifact and control APIs are unauthenticated while the server binds to `0.0.0.0` | Deployment safety gap |
| M1 | Medium | Workflow graph validation is incomplete and allows invalid entry/transition/dependency targets | Confirmed validation gap |
| M2 | Medium | `instances` is loaded and documented but never affects execution | Confirmed contract drift |
| M3 | Medium | Tasks in a submitted step execute sequentially despite architecture text saying elements run in parallel | Confirmed contract drift |
| M4 | Medium | Disabling every specialist in an element omits `task.completed` | Confirmed event/state defect |
| M5 | Medium | Specialist and gate configuration endpoints accept unknown compound keys or committee names | Confirmed validation gap |
| M6 | Medium | SSE supports only one live consumer per run and cannot reconstruct missed state | Known architecture limitation |
| M7 | Medium | Engagement records are memory-only, so restart makes persisted artifacts unreachable through the API | Known architecture limitation |
| M8 | Medium | Provider configuration is asymmetric across specialists, leaders, and report chat | Confirmed configuration gap |
| M9 | Medium | Report-chat context and history grow without a deterministic bound | Confirmed resource/control gap |
| L1 | Low | Documentation and event taxonomy have drifted from the implementation | Confirmed documentation drift |
| L2 | Low | Dead or disconnected observability surfaces remain in source | Confirmed maintenance debt |

---

## Detailed findings

### C1 — In-loop gate actions are fail-open

**Evidence**

- `src/athena/server/routes/loop_gate.py:58-84` accepts an arbitrary `action: str` and
  forwards it without validating it against the currently pending gate kind.
- `src/athena/harness/committee_runner.py:739-766` treats only the literal action `deny`
  as denial. Every other value, including a typo or an action intended for another gate kind,
  returns approval.
- The element and step gate helpers likewise treat unknown values as acceptance at
  `committee_runner.py:718-736` and `committee_runner.py:791-796`.

**Impact**

A stale client, malformed request, or UI/API version mismatch can release a pending tool gate
and execute the domain skill even though the operator did not send a valid approval. This is a
fail-open safety boundary.

**Recommendation**

Store the pending gate kind in `EngagementContext` alongside its decision slot. Validate at the
route boundary using exact action sets:

- element: `accept | override | redo`;
- step: `accept | redo | skip`;
- tool: `approve | deny`.

Require `winner_id` for `override`, reject fields irrelevant to the gate kind, and make the
committee-side helpers raise on an impossible action rather than defaulting to acceptance.
Add route tests proving every invalid cross-kind action returns `400` and does not set the event.

### H1 — A refused committee becomes a completed engagement

**Evidence**

- `src/athena/harness/workflow.py:123-130` catches `RefuseStartError`, publishes
  `engagement.rejected`, and returns `None` normally.
- `src/athena/server/runner.py:349-368` treats every normal return from `run_workflow()` as
  success and unconditionally sets `ctx.status = completed`.

**Impact**

The UI may receive a rejection event while the status endpoint and reconnect logic subsequently
report completion. Downstream automation cannot reliably distinguish refusal from success.

**Recommendation**

Give `run_workflow()` an explicit typed terminal result, for example
`WorkflowResult(status, reason)`, or let refusal propagate as a dedicated exception handled by
the runner. The runner must be the sole owner of the terminal status/event transition. Add an
integration test that drives `refuse_start` and asserts one terminal event and `rejected` status.

### H2 — Declared global and cross-committee iteration budgets are advisory only

**Evidence**

- `GLOBAL_STEP_BUDGET = 750` is declared at `src/athena/harness/workflow.py:44` and supplied to
  `run_workflow()` by `runner.py:350-363`.
- The `global_step_budget` parameter at `workflow.py:74` is never read.
- Retry and iterate counters are incremented at `workflow.py:232` and `workflow.py:257`, but no
  deterministic threshold is enforced.
- The orchestrator is merely told "of 3" and "of 30" in
  `src/athena/harness/orchestrator.py:519-522` and may still request more.

Per-committee `max_steps`, specialist iteration limits, and tool-call budgets are real controls;
the global and cross-committee limits are not.

**Impact**

A workflow can cycle indefinitely through declared retry/iterate edges, producing unbounded
model cost and preventing the single worker from becoming available. The documented "deterministic
iteration caps" claim is therefore only partly true.

**Recommendation**

Introduce a workflow-owned budget object. Decrement it for every accepted committee step and
enforce explicit `max_retries` and `max_iterations` before re-entering a node. Exhaustion should
produce a typed operator escalation or failed terminal result, never rely on the orchestrator to
self-regulate. Test self-loops and backward edges at the exact boundary.

### H3 — Engagement plans are schema-valid but not ensemble-valid

**Evidence**

- `src/athena/engagement_plan.py:26-61` validates only field shapes. The `Gate` docstring claims
  its `after` value is validated against the manifest at runtime, but no such validation exists.
- `src/athena/harness/orchestrator.py:355-386` accepts a plan after Pydantic validation alone.
- `src/athena/harness/workflow.py:91-93` silently supplies a generic brief if a manifest committee
  is missing from the plan.
- `workflow.py:154` only applies a gate whose string happens to equal the current node. Unknown
  gate names are silently ignored.

This matters most when a capability declares a mandatory gate. For example,
`tests/ensembles/redteamv1/capability.md:39-40` requires an approval gate after `planning`, but
that safety requirement is prose enforced by the orchestrator prompt, not a deterministic rail.

**Impact**

The orchestrator can omit committees, invent committee names, or mistype a mandatory gate and
still receive "Plan validated." A safety gate may silently not exist.

**Recommendation**

Add `validate_plan_for_ensemble(plan, ensemble)` before publishing `plan_ready`. At minimum:

- require the plan committee set to equal the reachable manifest committee set, unless an
  explicit optional-committee mechanism is added;
- reject unknown committee names and duplicate or unknown gate targets;
- validate gate types against declared manifest transitions;
- move mandatory gates from capability prose into manifest data and enforce their presence.

### H4 — Abort releases the single-engagement guard before execution has stopped

**Evidence**

- `src/athena/server/runner.py:424-446` immediately sets status to `abandoned` and wakes known
  waits.
- `is_busy()` at `runner.py:161-162` only considers contexts whose status is `running`, so a new
  engagement can be submitted immediately.
- The same function acknowledges that a worker inside an LLM call, leader `ask_operator`, or
  another non-interruptible operation may continue for some time.
- The executor has one worker, so the newly accepted engagement can remain queued behind the
  still-running abandoned engagement while the API reports it as started.

**Impact**

The one-engagement invariant becomes ambiguous: the old run may continue making model or tool
progress while a new run has already been admitted. The new UI can appear stuck because its job
is queued. If future concurrency is enabled, both runs could overlap.

**Recommendation**

Split lifecycle state into `cancelling` and terminal `abandoned`. Keep `is_busy()` true until the
worker exits and acknowledges cancellation. Return `202 cancelling` from abort, and expose a
completion event or pollable status. Add a cooperative cancellation callback to `run_agent()` and
specialist dispatch, checked before every model call and before every skill execution.

### H5 — The application is network-reachable without authentication

**Evidence**

- `server.py` binds to `0.0.0.0` by default.
- `src/athena/server/app.py:37-65` installs CORS but no authentication or authorization
  middleware.
- Engagement start, chat, gate decisions, specialist toggles, abort, artifact reads, report chat,
  and file-browser reveal are controlled only by knowledge of a `run_id`.
- Artifacts are read as plaintext by `src/athena/server/routes/artifacts.py:54-85`.

**Impact**

On any host where port 8000 is reachable, another network user can start or abort engagements,
steer leaders, approve gates, change specialist configuration, and read engagement artifacts.
The UUID is not an authorization mechanism.

**Recommendation**

For the prototype, default to `127.0.0.1` and require an explicit flag for external binding.
Before any shared or hosted deployment, add authenticated operator sessions, CSRF protection for
browser mutations, authorization on every engagement resource, TLS, and an audited artifact
access path. This aligns with the existing zero-trust design in
`projects/202609_ARTIFACT_ZEROTRUST.md`.

### M1 — The ensemble loader does not fully validate the workflow graph

**Evidence**

`src/athena/ensemble/loader.py:69-99` ensures that each workflow node has a matching committee,
but it does not verify:

- that `workflow.entry` exists as a node;
- that transition targets exist;
- that every committee has a workflow node;
- that transition conditions are recognized;
- that there is at most one unconditional forward transition;
- that required/optional `consumes` names exist and are reachable upstream;
- that skill IDs, committee names, element IDs, specialist IDs, or tool names are unique.

Several of these failures surface only during execution as `KeyError`, and duplicate registry
entries silently overwrite earlier definitions.

**Recommendation**

Add a complete load-time graph validation pass with descriptive `ValueError`s. Treat manifest
loading as the compilation boundary: a loaded ensemble should be safe to traverse without
structural checks at runtime. Add negative fixtures for every invariant.

### M2 — `instances` is a no-op manifest field

**Evidence**

- `src/athena/ensemble/loader.py:257-289` loads `instances`.
- `src/athena/ensemble/types.py:68-85` says the harness instantiates that number of specialists.
- Execution in `src/athena/harness/committee_runner.py:1127-1153` branches only on the number of
  specialist definitions; `element.instances` is never referenced.

**Impact**

Ensemble authors can configure a field that has no effect, producing a misleading manifest and
incorrect capacity/cost assumptions.

**Recommendation**

Either implement explicit instance expansion with stable IDs and selection semantics, or remove
the field from the types, loader, docs, and examples. Avoid retaining a configuration knob that
looks operational but is inert.

### M3 — Step tasks are sequential, not parallel

**Evidence**

- The architecture says elements in a committee step run in parallel
  (`doc/ARCHITECTURE.md:41-42` and the repository vocabulary).
- `_SUBMIT_STEP_TOOL` explicitly says tasks run sequentially at
  `src/athena/harness/committee_runner.py:67-71`.
- The implementation loops synchronously over tasks at `committee_runner.py:320-370`.
- Only variants within a compare element use a thread pool at `committee_runner.py:1098-1100`.

**Impact**

Latency and model/tool scheduling differ materially from the documented execution model. It also
changes how concurrent in-loop gates and rate limits should be reasoned about.

**Recommendation**

Make a product decision and align all layers. If step tasks should run in parallel, dispatch each
task with a bounded executor, preserve deterministic output ordering, and keep the existing
loop-gate serialization. If sequential execution is intentional, update architecture and ensemble
guidance.

### M4 — Fully disabled elements never emit task completion

**Evidence**

In `src/athena/harness/committee_runner.py:333-346`, if all specialists in an element are
disabled, the code appends a textual result and immediately `continue`s. The normal
`task.completed` event at lines 362-369 is skipped.

**Impact**

The UI and audit stream see `task.started` without a matching terminal event. A step can complete
while one of its displayed tasks remains active indefinitely.

**Recommendation**

Emit `task.completed` with a structured status such as `skipped` and the reason. Prefer adding a
task outcome field rather than representing disabled execution only as free text returned to the
leader.

### M5 — Runtime configuration accepts unknown targets

**Evidence**

- `runner.arm_gate()` at `src/athena/server/runner.py:462-473` creates an entry for any committee
  string.
- `POST /loop-gate-arm` validates the kind but not the committee at
  `src/athena/server/routes/loop_gate.py:87-109`.
- `runner.set_specialist_enabled()` at `runner.py:519-527` accepts any compound key, and the
  specialist configuration route echoes success.

**Impact**

Typos and stale clients receive successful responses while changing nothing. The operator may
believe a safety review is armed or a specialist is disabled when it is not.

**Recommendation**

Resolve both targets against `ctx.ensemble` before mutation. Return `404` for unknown committee,
element, or specialist components, and add one canonical compound-key parser shared by the
manifest serializer and route logic.

### M6 — SSE is lossy and single-consumer

**Evidence**

- `src/athena/server/bus.py:40-44` stores one queue per `run_id`; a second connection replaces
  the first.
- The old queue then stops receiving events, while its stream remains open on heartbeats.
- Events published before a queue exists or during reconnect are dropped at `bus.py:61-71`.
- `src/athena/server/routes/events.py:41-48` reconstructs only a generic terminal topic, without
  the rejection reason or any intermediate state.

**Impact**

Opening a second tab silently freezes the first. A reconnect can miss gates, agent state, tool
history, and committee results. The reducer cannot reconstruct the dashboard from the status
endpoint, which exposes only `run_id` and `status`.

**Recommendation**

For a local single-tab prototype, explicitly enforce one SSE client and tell the displaced
client. For a robust UI, use a per-run set of subscriber queues plus a bounded event journal with
monotonic sequence IDs and `Last-Event-ID` replay. Also provide a snapshot endpoint capable of
rehydrating reducer state.

### M7 — Engagement metadata is not durable

**Evidence**

- Active contexts live only in `_active` at `src/athena/server/runner.py:57-58`.
- Artifact and SSE routes first require an in-memory context at
  `src/athena/server/routes/artifacts.py:41-67` and
  `src/athena/server/routes/events.py:35-39`.
- Artifacts remain on disk after restart, but their engagement IDs are no longer recognized.

**Impact**

Server restart loses status, plan, ensemble identity, disabled-specialist state, gate state, and
API access to existing artifacts. The system cannot yet support history, chaining, recovery, or
reliable audit.

**Recommendation**

Implement the durable engagement record proposed as EN0 in
`projects/202609_ENGAGEMENT_CHAINING.md`. Load terminal records at startup, use the record rather
than `_active` as the authorization/existence check for artifact access, and keep `_active` as a
cache only for live execution state.

### M8 — Provider configuration is inconsistent across agent roles

**Evidence**

- `LoadedSpecialist` carries per-endpoint `base_url` and `auth_headers_env` in
  `src/athena/ensemble/types.py:41-65`; `_ollama_transport()` resolves them for specialists.
- `LoadedCommittee` has only `model` and `provider` (`types.py:88-107`). Its leader is constructed
  with `make_backend(committee.provider)` and no configuration at
  `src/athena/harness/committee_runner.py:611`.
- Report chat reads a provider and model but calls `make_backend(report_provider)` without a
  provider configuration at `src/athena/server/routes/report_chat.py:89-92`.
- The top-level orchestrator has a separate JSON configuration environment variable.

**Impact**

OpenAI-compatible providers work for specialists and the orchestrator but cannot be configured
equivalently for committee leaders or report chat. The README's "bring your own model" claim is
therefore broader than the implemented role coverage.

**Recommendation**

Introduce one provider-neutral `BackendConfig` resolved at load/start boundaries and attach it
to every role that creates a backend. Keep secret values in environment variables, but centralize
the mapping from declarative config to backend factory arguments.

### M9 — Report-chat context grows without a hard bound

**Evidence**

- Every artifact is inserted in full for every question at
  `src/athena/server/routes/report_chat.py:62-87`.
- Every prior question and full answer is also appended.
- `_history` is process-global and never pruned at lines 34-35 and 97.
- The model output is capped, but input size and number of exchanges are not.

**Impact**

Long engagements or repeated debrief questions can exceed provider context limits, increase cost,
retain sensitive data in process indefinitely, and eventually fail the endpoint.

**Recommendation**

Set deterministic artifact byte/token ceilings, bound exchanges per run, summarize or window old
turns, and clear history according to engagement retention policy. Report-chat configuration
should also use the unified provider configuration described in M8.

### L1 — Documentation and event contracts have drifted

Examples include:

- `doc/ARCHITECTURE.md:15-16` documents `/gate` and `/loop-gate`, while current routes are
  `/gate-decision` and `/loop-gate-decision`.
- The architecture describes a module-level `_ctx`, while current code uses `_active`.
- It says elements in a step run in parallel, while the implementation is sequential.
- The SSE taxonomy in prose omits current topics such as `engagement.started`, `plan_ready`,
  `gate.awaiting_approval`, `gate.decision`, loop-gate events, and artifact emission.
- `server.py`'s module docstring still names legacy environment variables while `env_vars.py` and
  the README use the `ATHENA_*` names.
- Some older `projects/` documents describe previously deferred behavior that now exists.

**Impact**

Coding agents and maintainers can implement against obsolete routes, state fields, or execution
semantics. In a system where topic names and gate phases are contracts, stale docs are a
correctness risk.

**Recommendation**

Regenerate `doc/ARCHITECTURE.md` and `doc/TERMS.md` from the current code after the high-priority
fixes. Add tests that compare documented route/topic inventories to source constants where
practical. Mark historical project documents as historical rather than authoritative.

### L2 — Observability surfaces are disconnected

**Evidence**

- `RunLogger` is tested but not used by the running harness.
- `COMMITTEE_ARTIFACT_EMITTED` exists in `topics.py` but no production publisher was found.
- The React reducer handles `agent.finding`, but no current production publisher was found in
  `src/athena`.

**Impact**

The apparent audit/event surface is larger than the live one. Maintainers may assume run logs,
artifact-emission events, or finding classifications are available when they are not.

**Recommendation**

Either wire each surface through the canonical execution path or remove it. The preferred order
is to introduce the single `ArtifactStore` seam proposed in the zero-trust plan, publish artifact
events from that seam, and make audit logging part of the same lifecycle.

---

## Positive controls verified

The following are real implementation strengths and should be preserved during refactoring:

1. **One provider-neutral agent loop.** `run_agent()` owns conversation iteration, tool result
   recording, max-token failure, end-turn correction, and operator-message injection.
2. **Per-specialist skill grants.** Only manifest-declared skills become tool definitions for a
   specialist; unknown skills are rejected by dispatch.
3. **Executed-call and attempt budgets.** Approved tool executions and operator-denied attempts
   are bounded separately, so a denial does not consume the execution budget but cannot create an
   unlimited prompt loop.
4. **Pre-execution tool gate placement.** When armed and given a valid decision, the tool gate
   runs before the deterministic skill implementation.
5. **Typed committee artifacts.** Leaders cannot finish successfully until their output validates
   against the committee Pydantic schema; malformed end turns are re-prompted within a bounded
   correction loop.
6. **Manifest-enveloped workflow decisions.** Retry and iterate targets are checked against
   declared transitions before traversal.
7. **Thread/async separation.** The blocking harness is kept off the FastAPI event loop, and
   PyPubSub crosses into asyncio with `call_soon_threadsafe`.
8. **Distinct await phases.** Plan, committee, and in-loop gate routes guard against posting into
   the wrong decision channel.
9. **Compare-mode fault tolerance.** One failing specialist variant does not sink the element;
   every variant must fail before the element fails.
10. **Benign skill scoping.** The inventory ensemble's filesystem skills resolve paths, enforce
    allowed roots, avoid following symlinks, and do not read file contents.

## Test assessment

The repository contains 188 discovered unit-test functions. Coverage is strongest around:

- the agent loop and backend normalization;
- ensemble loading happy paths;
- compare-mode selection and variant failure;
- tool, step, and element gate helpers;
- loop-gate route phase guards;
- shared payload limits and topic constants;
- artifact logger helpers and collaboration parsing.

The most important missing tests are end-to-end lifecycle assertions:

- refusal must remain rejected;
- workflow budget exhaustion;
- retry and iterate caps;
- plan-to-ensemble semantic validation and mandatory gates;
- invalid gate actions must remain blocked;
- abort acknowledgement before admitting a new run;
- SSE multiple subscribers, disconnect/reconnect, and snapshot recovery;
- all-disabled task event balance;
- loader negative graph cases;
- restart access to durable terminal engagements.

The unit suite could not be executed in this audit environment because `pytest` was not installed
on `PATH`. No dependency installation was attempted. The findings above are therefore based on
source tracing and static cross-reference, not a fresh green test run.

## Recommended remediation order

### Phase 0 — Safety and terminal correctness

1. Fix C1 with typed per-kind loop-gate decisions and fail-closed helpers.
2. Fix H1 by giving the workflow an explicit terminal result owned by the runner.
3. Add plan-to-ensemble validation and manifest-declared mandatory gates (H3).
4. Add regression tests for those three paths before further feature work.

### Phase 1 — Deterministic bounded execution

1. Implement the global workflow budget and hard retry/iterate caps (H2).
2. Make cancellation acknowledged and cooperative before admitting a new run (H4).
3. Complete loader graph validation (M1).
4. Resolve or remove `instances`, and decide whether step tasks are parallel (M2/M3).

### Phase 2 — Durable and secure local product

1. Introduce the behavior-preserving `ArtifactStore` seam.
2. Add durable engagement records and terminal-run recovery (M7).
3. Default to localhost; add authentication before any external bind (H5).
4. Add encryption, retention, and audited artifact access following the existing zero-trust plan.

### Phase 3 — Robust operator experience

1. Add event IDs, replay, multi-subscriber SSE, and a state snapshot endpoint (M6).
2. Validate runtime specialist/gate target mutations (M5).
3. Balance task events for skipped/disabled work (M4).
4. Bound report-chat context and unify provider configuration (M8/M9).
5. Update canonical documentation and remove or wire dead event surfaces (L1/L2).

## Final conclusion

Athena's underlying idea is technically sound: declarative ensembles plus deterministic
orchestration are a much better control model than relying on a general agent framework to
self-police. The prototype already has several load-bearing rails, especially schema validation,
least-privilege skill grants, bounded specialist execution, explicit gates, and a clean
thread-to-SSE bridge.

The next work should focus on making every claimed control mechanically true. In particular,
gate decisions must fail closed, terminal outcomes must be unambiguous, and all global iteration
limits and mandatory gates must move out of model prompts and into deterministic validation. Once
those are fixed, the already-proposed artifact-store and durable-engagement seams are the right
foundation for marketplace, chaining, and zero-trust work.
