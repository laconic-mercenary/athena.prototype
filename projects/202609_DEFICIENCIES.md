# 2026-09 Deficiencies & Pre-Work Punch List

General cleanups and open questions to resolve **before** undertaking the next round of
serious work. Companion to [[HARNESS_DEFICIENCIES.md]] (implementation defects) and
[[ENSEMBLE_DEFICIENCIES.md]] (scale/design gaps D1–D8). This file is the running punch list
captured after the demo.

Status legend: **ACCEPTED** (known, fine for now) · **OPEN** (needs decision) · **FIXED** ·
**VERIFY** (needs a live check).

---

## Operator UX / rendering

### UX1 — Render markdown in the chat windows · OPEN
Agent/leader/operator messages in the chat panels render as raw text. The report viewer already
renders markdown (`marked.parse()` in [ReportModal](../src/ui/src/components/ReportModal.jsx));
the chat surfaces do not, so lists, code fences, and emphasis show as literal characters.
**Direction:** reuse the `.md-render` path (same `marked.parse()` + styles) in the chat message
component. Sanitize before injecting HTML. Keep raw-text fallback for tool/system lines.

### UX2 — Add multiple-choice selection for the operator · OPEN
The operator can only free-type or accept/redo. Some gates would be clearer as a constrained
pick-one-of-N (e.g. "which vector to pursue", "pick the winning artifact"). No structured
choice control exists today.
**Direction:** a gate payload variant carrying `options: [...]`; UI renders a radio group;
decision routes back through the existing gate-decision channel. Ties to how gates are typed —
see ARCH-level system-view overhaul (ARCH3).

### UX3 — Add Yes/No boolean selections for the operator · OPEN
Related to UX2: a first-class boolean gate (confirm / deny) instead of overloading the free-text
box or accept/redo. Lower effort than UX2 and a good first cut of structured gate inputs.
**Direction:** same gate-payload mechanism as UX2 with `kind: boolean`; two buttons.

---

## Legal / packaging

### LEG1 — Add LICENSE (MIT) · OPEN
Repo has no LICENSE file. Add MIT at the repo root.
**Direction:** standard MIT text, current year, appropriate copyright holder. Confirm holder
name before writing.

---

## Architecture / system

### ARCH1 — API and the UI: what situation are we in? · OPEN (investigate)
Clarify the current split and coupling between the FastAPI backend and the React UI — what's
served how, what the deployment/runtime story is (containerized `run.sh` vs dev), and where the
seams are. Output a short "current state" writeup before any restructuring.
**Direction:** document the actual wiring (server routes ↔ SSE bus ↔ UI state) as-is, then
identify what's brittle. No code change until the picture is written down.

### ARCH2 — Env vars are provider-specific: how deep in the harness do they exist? · OPEN (investigate)
Provider auth/config is threaded through several layers — global `ATHENA_OLLAMA_*`, per-specialist
`ollama_base_url` + `auth_headers_env` (Kimi/Modal), Anthropic keys, plus the newer
`TOOLS_HTTP_OK_DOMAINS`. Map exactly where each provider-specific env var is read and how deep
the coupling goes ([model_backend.py](../src/athena/model_backend.py),
[loader.py](../src/athena/ensemble/loader.py), skills).
**Direction:** produce a table of env var → read site → layer. Assess whether provider config
should be centralized/abstracted behind a config layer rather than read ad hoc.

### ARCH3 — System view needs overhaul · OPEN
The current "system view" (how the running engagement, committees, gates, and threads are
represented to the operator) needs a rethink — it's grown organically. This is the larger item
that UX1–UX3 feed into (typed gates, structured decisions, clearer state).
**Direction:** scope a redesign after ARCH1/ARCH2 are documented. Likely touches the SSE event
model, gate typing, and the dashboard/graph representation. Treat as a project, not a patch.

---

## Notes
- UX1–UX3 and ARCH3 are related: structured operator inputs are a subset of the system-view
  overhaul. Sequence: land UX1 (cheap win) → document ARCH1/ARCH2 → design ARCH3 → UX2/UX3 fall
  out of the typed-gate work.
- LEG1 is independent and quick.
