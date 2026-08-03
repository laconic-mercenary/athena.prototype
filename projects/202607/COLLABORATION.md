# COLLABORATION

Mid-engagement co-approval by an external collaborator, triggered by the operator at an approval gate.

---

## Goal

Allow the operator to invite an external collaborator to co-approve a gate decision mid-engagement. The collaborator receives an email, reads a summary of the engagement and the relevant chat context, and replies with their decision. The engagement remains paused until the reply arrives.

---

## Terms

**Operator** — same as always; initiates the collaboration request by mentioning a collaborator at a gate.

**Collaborator** — an external email user with co-approval rights only. Can approve or deny. Cannot provide instructional input to the harness or any model. The system ignores all reply content except the approve/deny keyword.

---

## User Flow

1. Engagement reaches an approval gate.
2. Operator types `@alias` in the gate input and hits Approve.
3. The server resolves the alias to an email address and sends a Resend email containing:
   - A summary of the engagement so far
   - The chat context where the `@` was entered
4. The UI transitions the gate panel to **"awaiting @alias"** with a sent timestamp.
5. The collaborator reads the email and replies with `approve` or `deny` (case-insensitive, anywhere in the reply body).
6. Resend routes the inbound reply to the Athena webhook.
7. The webhook parses the keyword and resumes the gate with the collaborator's decision.
8. The engagement proceeds (advance) or halts (deny).

---

## Architecture

### Alias resolution

A single env var — `COLLABORATOR_ALIASES` — holds a comma-separated list of `alias:email` pairs:

```
COLLABORATOR_ALIASES=alice:alice@company.com,bob:bob@example.com
```

Parsed at server startup into a dict. Unknown aliases return an error to the operator immediately (before sending anything).

### Gate mechanism

The existing operator gate already pauses on a `queue.Queue` in the runner thread. Collaborator approval uses the **same queue** — the only difference is what puts the decision in:

- Normal flow: operator clicks Approve/Deny → API handler → queue
- Collaboration flow: operator's `@alias` + Approve → email sent → queue stays blocked → inbound webhook → queue

The runner thread never knows the difference.

### In-memory state

A server-level dict tracks pending collaborations:

```python
pending_collabs: dict[str, CollabState]  # keyed by run_id
```

```python
@dataclass
class CollabState:
    run_id:    str
    alias:     str
    email:     str
    sent_at:   datetime
    gate_queue: queue.Queue
```

Lost on server restart — acceptable for demo.

### New server endpoints

**Modified:** `POST /api/engage/{run_id}/gate`
- If the request body contains `@alias`, branch into the collaboration flow instead of resolving the gate immediately.
- Resolve alias → email; error if unknown.
- Send Resend email.
- Store `CollabState` in `pending_collabs`.
- Emit `engagement.collaborator_pending` SSE event (alias + sent_at).
- Return 202 — gate is now pending, not resolved.

**Implemented:** `POST /webhooks/inbound-email` (Resend `email.received` webhook)
- Verifies the Svix signature over the raw body (`svix-id`/`svix-timestamp`/`svix-signature`,
  HMAC-SHA256 with `RESEND_WEBHOOK_SECRET`). Unverified → 401. No secret configured → refuse.
- Extracts `run_id` from the recipient (`<run_id>@<COLLAB_REPLY_DOMAIN>`) via the per-run
  `reply_to`. Wrong/absent domain → 200 ignore.
- The webhook carries **metadata only** — fetches the body separately via
  `GET https://api.resend.com/emails/receiving/{email_id}` (`text`, falls back to
  tag-stripped `html`).
- Parses the reply for `approve` / `deny` (or `reject`), scanning **only the text above the
  first quoted-original marker** so "reply APPROVE or DENY" in the quoted email can't
  false-match. Ambiguous (both / neither) → 200, gate stays parked.
- On a clear decision: `pop()` the `CollabState` (only then — an ambiguous reply leaves the
  re-reply/link path intact), then `runner.resolve_approval(approved=...)`.
- Returns 200 for intentional no-ops (wrong event, no run_id, no decision, already resolved)
  so Resend doesn't retry; 500 only on a transient body-fetch failure worth retrying.

### Email (Resend)

**Outbound**
- To: collaborator email · Subject: `[Athena] Co-approval requested (@alias)`
- **Primary path — reply-in-email:** when `COLLAB_REPLY_DOMAIN` is set, the email leads with
  "reply with APPROVE or DENY" and carries `reply_to: <run_id>@<COLLAB_REPLY_DOMAIN>`. The
  collaborator just hits Reply — no link click needed (dodges clients that mangle links).
- **Operator's message** (the text they `@`-mentioned the collaborator in) renders in a
  highlighted quote block at the top — the "why".
- **Attachment:** `plan-briefing.txt` — the plan rendered as readable prose (not raw JSON),
  base64-encoded via Resend's `attachments` field.
- **Fallback:** the `GET .../approve` and `/deny` links remain below the reply CTA. When
  `COLLAB_REPLY_DOMAIN` is unset, no `reply_to` is added and the links are the only path.
- Reply-in-email uses the **Resend-managed receiving domain** (`<id>.resend.app`) — no
  MX/DNS setup; Resend receives every local-part at that domain, giving per-run addressing.

**Approve / deny endpoints**
- `GET /webhooks/collab/{run_id}/approve` — releases the gate with approved=True, returns a confirmation page
- `GET /webhooks/collab/{run_id}/deny` — releases the gate with approved=False, returns a confirmation page
- Links are single-use; a second click returns HTTP 410 with "Already recorded"
- The `run_id` UUID is unguessable and serves as the access token

### UI changes

- Gate input: detect `@word` pattern; visual hint that collaboration mode will be triggered
- On `engagement.collaborator_pending` event: replace the gate panel with an **"Awaiting @alias"** view showing alias, email, and sent timestamp
- Operator retains a cancel/retract option (TBD — not in scope for demo)

---

## Committee-gate collaboration (demo focus)

The shipped feature co-approves the **plan** gate. The demo extends the same mechanism to
the **committee gate** (the between-committee operator gate, Accept / Redo). Design:

### Shared gate textbox, routed by button

The committee gate has one operator textbox, shared by both actions. Where the text goes
depends on which button is pressed — routing is by the **button, not the box**:

| Button | Text contains `@`? | Destination |
|---|---|---|
| **Redo** | (ignored) | The leader, as redo feedback — operator input to a model (allowed) |
| **Approve** | yes | First `@token` → collaborator alias; remaining text → human note in the email |
| **Approve** | no | Discarded — an accept has nothing to feed |

Approve text only ever reaches a *human* (the email) or is dropped; it never reaches a
model. Only Redo text reaches a model, and that is operator-authored (allowed).

### Two approvals to advance

Advancing past the gate takes two approvals: the operator's (implicit in clicking Approve
with an `@alias`) and the collaborator's (the email link click). Clicking Approve with an
alias does **not** resolve the gate — it records the operator's approval and parks as
`collaborator_pending`; the collaborator's link click is the second approval, which calls
`resolve_gate_decision(action="accept")`. Redo advances nothing, so it stays single-party
(operator only). A collaborator Deny releases the gate as a feedback-less Redo (see
Known deficiencies).

### Context delivered to the collaborator

Enough to make a real decision — objective (the "why") plus the digest (the "what"):

- **Email body:** the engagement objective (one line, from `ctx.orchestrator`'s plan) +
  the operator's note + the Approve / Deny buttons.
- **Attachment:** `engagement-summary.txt` — the full committee **digest**
  (`artifact.render_digest()`, the same string the operator approves) plus the objective.
  Plain text, base64-encoded via Resend's `attachments` field. Keeps the body short.

### State & dispatch

- `CollabState` gains a **gate-kind discriminator** (`"plan"` | `"committee"`) so the link
  handler dispatches to `resolve_approval` (plan) vs
  `resolve_gate_decision(action="accept" | "redo")` (committee).
- Confirmation-page copy is neutralized (`Approved` / `Denied`, not `Plan approved`).
- The "Awaiting @alias" pending view is replicated on the committee-gate surface — a
  different component than the plan gate.
- One pending collaboration per run at a time (single `_pending[run_id]` slot); fine for
  sequential gates (see Known deficiencies).

---

## Constraints

- Collaborator decision content is never passed to any model. Only the approve/deny link click is consumed.
- One collaborator per gate invocation (no multi-party for demo).
- The run_id UUID in the link serves as the access token — no separate HMAC for demo.
- Engagement pauses indefinitely — no timeout for demo.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `COLLABORATION_ENABLED` | No | Set to `true` to enable the feature. Any other value (or absent) disables it — `@alias` mentions at gates are ignored and the endpoints return 404. |
| `COLLABORATOR_ALIASES` | If enabled | Comma-separated `alias:email` pairs. e.g. `alice:alice@co.com,bob:bob@co.com` |
| `RESEND_API_KEY` | If enabled | Resend API key. Used for both sending outbound email and fetching inbound reply bodies (`/emails/receiving/{id}`). |
| `ATHENA_BASE_URL` | If enabled | Public base URL of the Athena server, e.g. `https://athena.openintel.to`. Used to build the approve/deny fallback links. |
| `COLLAB_REPLY_DOMAIN` | For reply-in-email | Resend-managed receiving domain, e.g. `cool-hedgehog.resend.app`. Enables the reply-in-email path (`reply_to: <run_id>@<domain>`). Unset → link-only fallback, no MX needed. |
| `RESEND_WEBHOOK_SECRET` | For reply-in-email | Svix signing secret (`whsec_…`) shown when the `email.received` webhook is created. Verifies inbound webhook authenticity; without it inbound replies are refused. |

---

## How `COLLABORATION_ENABLED` is enforced in code

> **Status:** feature not yet implemented — this section is the implementation spec.

A single helper reads the flag at import time:

```python
# src/athena/collaboration.py
import os

COLLABORATION_ENABLED = os.environ.get("COLLABORATION_ENABLED", "").strip().lower() == "true"
```

This boolean is imported and checked in two places:

**1. Gate endpoint (`server/runner.py` or the gate API handler)**
When the operator submits a gate decision containing `@alias`, the handler checks `COLLABORATION_ENABLED` before branching into the collab flow:

```python
from athena.collaboration import COLLABORATION_ENABLED

if "@" in decision_text and COLLABORATION_ENABLED:
    # collab flow — resolve alias, send email, park the queue
else:
    # normal gate resolution
```

If `COLLABORATION_ENABLED` is false, the `@alias` text is treated as a plain comment and the gate resolves normally as an operator decision.

**2. Inbound webhook (`POST /webhooks/inbound-email`)**
The route is registered conditionally — it only exists when the feature is enabled:

```python
if COLLABORATION_ENABLED:
    @router.post("/webhooks/inbound-email")
    async def inbound_email(request: Request): ...
```

If disabled, the endpoint is never registered and returns 404 naturally — no explicit guard needed inside the handler.

---

## Resend.com setup (one-time)

### 1. Get an API key

Go to **API Keys → Create API Key** in the Resend dashboard. Name it `athena-collab`, permission: **Sending access**. Copy the key — shown once.

### 2. Confirm domain is verified

`openintel.to` is already in Resend with DKIM set up. Outbound from `athena@openintel.to` is ready. No further DNS changes needed — the link approach requires no inbound MX records.

### 3. Update `.env`

```
COLLABORATION_ENABLED=true
RESEND_API_KEY=re_...
COLLABORATOR_ALIASES=alice:alice@company.com,bob:bob@example.com
ATHENA_BASE_URL=https://athena.openintel.to
```

### 4. Test

Send a test engagement, enter `@alice` in the collaborator field, and click Co-Approve. Check that the email arrives at the collaborator's inbox with working approve/deny buttons.

---

## Known deficiencies (demo)

These are accepted shortcuts for the demo, to be revisited.

- **Committee-gate collaborator Deny is a feedback-less Redo.** The committee gate's
  negative action is *Redo*, not *reject*, and a collaborator has no text channel — so a
  collaborator Deny releases the gate as `redo` with no suggestion. The committee re-runs
  blind, but the leader typically asks a clarifying question shortly, which makes the
  redo interactive. This reuses the existing `redo` action (no new reject/halt path).
  Ideal: let the collaborator attach a reason to the Redo.
- **Only the Accept/advance path is co-approved; Redo is single-party.** "Two approvals
  to progress" applies to advancement only. Redo does not advance the workflow (it loops
  back), so the operator may Redo unilaterally without a second approval. The "ask a
  collaborator to sign off on a Redo" case is real but out of scope.
- **One collaboration per run at a time.** Pending collaborations are stored keyed by
  `run_id` (single slot). Since gates occur sequentially, only one can be pending at a
  time — acceptable for the demo, but two concurrent collaborations on one run would
  collide.
- **Approve-note text is discarded when no `@` is present.** The shared gate textbox
  routes by button: Redo text → the leader (model); Approve text with an `@` → the
  collaborator email (human); Approve text with no `@` → silently dropped (an accept has
  nothing to feed). An operator who types a note on a plain Approve won't see it go
  anywhere.

## Open items

- Operator cancel/retract while waiting for collaborator (out of scope for demo).
- What the UI shows to the operator if the collaborator denies — currently just halts the gate, same as operator deny.
- Multi-collaborator (out of scope).
