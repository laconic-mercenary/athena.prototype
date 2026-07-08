# WORKSPACE_TODO.md — Known Deficiencies and Deferred Work

Items that are out of scope for Phase 1 but must not be forgotten.
Update this file as deficiencies are resolved or new ones are identified.

---

## UI / UX

- **Dashboard outside of an engagement run is undefined.** The Dashboard is only
  valid while an engagement is active. Navigating to it with no run in progress
  has no specified behaviour. Needs an empty state or a redirect to Engagement
  Request. Deferred.

- **"Draw relationships" goal (WORKSPACE_UI.md Goal #4) is unimplemented.**
  The goal states operators should be able to draw relationships between entities
  that agents cannot see. No concrete design exists for what this means in the UI
  (annotation, manual edges, linked findings?). Deferred until the goal is defined.

- **Agent termination (Terminate button) is non-functional in Phase 1.**
  The Terminate option appears in the specialist context menu but does nothing.
  Implementing it requires a cooperative stop flag in the agent loop checked
  between iterations. Phase 2.

- **Operator Chat is one-way in Phase 1 (orchestrator only).**
  Chat with individual committee leaders mid-run is not implemented. The pipeline
  has no mechanism to inject operator input into a running committee. Phase 2.

---

## Data / Schema

- **RetrievalArtifact has no criticality field.**
  `RetrievedFinding` carries no classification. The Artifact Table cannot sort the
  retrieval artifact by criticality without either: (a) deriving it from the linked
  `PlanArtifact` action priorities via `action_id`, or (b) adding a top-level
  `risk_rating` field to `RetrievalArtifact`. Deferred; retrieval artifact sorts
  last by default in Phase 1.

- **"Who collected" attribution is committee-level only.**
  The Artifact Table metadata dialog shows "who collected." Phase 1 derives this
  from the committee name (recon, planning, etc.). Per-specialist attribution
  (which specific specialist agent produced a finding) requires plumbing specialist
  IDs into the artifact serve endpoint. Deferred.

---

## Backend / Pipeline

- **Mid-pipeline operator input gates are not supported.**
  Blocking the pipeline thread (Phase 1 `ask_user` approach) cannot be used between
  committees — it would freeze agents in flight. A different mechanism (async
  checkpoint nodes) is required. Deferred until needed.

- **Pre-flight clarification UI (Option C) not implemented.**
  Phase 1 uses Option B (thread block on `ask_user`). Option C — a separate
  clarification phase before the pipeline starts, with proper async Operator Chat —
  is the cleaner long-term UX. Replace Option B when implemented.

- **SSE stream replay on reconnect is not implemented.**
  If the operator's browser disconnects and reconnects mid-engagement, events
  fired during the gap are lost. The `asyncio.Queue` is not persistent. A simple
  fix is an in-memory event log per engagement that replays on reconnect. Deferred.
