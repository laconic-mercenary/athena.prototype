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

**New:** `POST /webhooks/inbound-email`
- Receives Resend inbound payload.
- Extracts `run_id` from the `To` address (`<run_id>@reply.openintel.to`).
- Looks up `CollabState` in `pending_collabs`.
- Scans reply body (case-insensitive) for `approve` or `deny`.
- Puts the decision into the gate queue.
- Removes entry from `pending_collabs`.
- Returns 200.

### Email (Resend)

**Outbound**
- To: collaborator email
- Subject: `[Athena] Co-approval requested (@alias)`
- Body (HTML): plan summary + two clickable buttons — **✓ Approve** and **✗ Deny**
- Each button links to `GET {ATHENA_BASE_URL}/webhooks/collab/{run_id}/approve` (or `/deny`)
- No inbound email or MX records required — the decision arrives as a browser GET request

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
| `RESEND_API_KEY` | If enabled | Resend API key for sending outbound email. |
| `ATHENA_BASE_URL` | If enabled | Public base URL of the Athena server, e.g. `https://athena.openintel.to`. Used to build the approve/deny links in the email. |

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

## Open items

- Operator cancel/retract while waiting for collaborator (out of scope for demo).
- What the UI shows to the operator if the collaborator denies — currently just halts the gate, same as operator deny.
- Multi-collaborator (out of scope).
