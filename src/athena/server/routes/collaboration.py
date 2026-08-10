"""GET /webhooks/collab/{run_id}/{decision} — link-based co-approval for plan gate.

Registered only when COLLABORATION_ENABLED=true (via app.py). The collaborator
clicks the approve or deny link from the email; this handler releases the plan
review gate and returns a simple confirmation page.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import HTMLResponse
from pubsub import pub

from athena import topics

from athena import collaboration
from athena.server import runner


###############
# CONSTS / GLOBALS #
###############

_log = logging.getLogger("athena.server.routes.collaboration")

router = APIRouter()


###############
# FUNCTIONS #
###############

@router.get("/webhooks/collab/{run_id}/approve")
async def collab_approve(run_id: str) -> HTMLResponse:
    return _resolve(run_id, approved=True)


@router.get("/webhooks/collab/{run_id}/deny")
async def collab_deny(run_id: str) -> HTMLResponse:
    return _resolve(run_id, approved=False)


@router.post("/webhooks/inbound-email")
async def inbound_email(request: Request) -> Response:
    """Resend email.received webhook — the collaborator replied to the co-approval
    email with APPROVE or DENY. Verify the signature, correlate the reply to its
    engagement by the per-run recipient address, fetch the body, and release the
    plan gate. Returns 200 for anything we intentionally ignore (wrong event, no
    run_id, no clear decision, already resolved) so Resend doesn't retry those;
    500 only on unexpected failures worth retrying.
    """
    body = await request.body()
    # Arrival log (before signature check) so "webhook never reached us" is distinguishable in
    # the logs from "reached us but failed verification/correlation".
    _log.info("inbound-email: webhook received (%d bytes, secret_configured=%s)",
              len(body), collaboration.webhook_secret_configured())
    if not collaboration.verify_webhook_signature(body, dict(request.headers)):
        _log.warning("inbound-email: signature verification failed — rejecting")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = json.loads(body)
    except ValueError:
        _log.warning("inbound-email: body is not valid JSON")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    if payload.get("type") != "email.received":
        return Response(status_code=status.HTTP_200_OK)  # not our event; ack and ignore

    data = payload.get("data") or {}
    run_id = collaboration.extract_run_id(data.get("to") or [])
    if not run_id:
        _log.info("inbound-email: no run_id in recipients %r — ignoring", data.get("to"))
        return Response(status_code=status.HTTP_200_OK)

    email_id = data.get("email_id")
    if not email_id:
        _log.warning("inbound-email: %r had no email_id — cannot fetch body", run_id)
        return Response(status_code=status.HTTP_200_OK)

    # Peek (don't consume): we surface the collaborator's message even when the reply
    # carries no clear decision, and only consume+resolve when it does.
    state = collaboration.get(run_id)
    if state is None:
        _log.info("inbound-email: %r already resolved or unknown — ignoring", run_id)
        return Response(status_code=status.HTTP_200_OK)

    try:
        text = await collaboration.fetch_received_email_text(email_id)
    except Exception:
        _log.exception("inbound-email: failed to fetch body for %r", run_id)
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)  # transient — let Resend retry

    decision = collaboration.parse_reply_decision(text)
    message = collaboration.reply_message(text)
    kw = "approve" if decision is True else "deny" if decision is False else "comment"

    # Always surface the collaborator's message to the chat. "comment" replies (no clear
    # keyword) show up too, so a collaborator's question is visible while the gate stays parked.
    pub.sendMessage(
        topics.COLLABORATOR_REPLIED,
        run_id=run_id,
        alias=state.alias,
        kind=state.kind,
        committee=state.committee,
        decision=kw,
        message=message,
    )

    # A committee gate runs "until APPROVE": only an approve resolves it — a DENY or a comment
    # stays parked and is surfaced as chat so the operator can keep the thread going. The plan
    # gate keeps its original approve/deny behaviour.
    if state.kind == "committee":
        resolves = decision is True
    else:
        resolves = decision is not None

    if not resolves:
        _log.info("inbound-email: %s from %s for %r — gate stays parked", kw, state.email, run_id)
        return Response(status_code=status.HTTP_200_OK)

    # Actionable decision — consume the pending state and release the gate.
    collaboration.pop(run_id)
    try:
        _dispatch_decision(state, approved=decision)
    except KeyError:
        _log.warning("inbound-email: engagement %r not found or already resolved", run_id)

    _log.info("collaboration (%s) for %r resolved via email reply: %s by %s", state.kind, run_id, kw, state.email)
    return Response(status_code=status.HTTP_200_OK)


###############
# NON PUBLIC FUNCTIONS #
###############

def _page(title: str, heading: str, color: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html><head><title>Athena — {title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Menlo,Monaco,Consolas,monospace;background:#0b1120;color:#e2e8f0;
     display:flex;align-items:center;justify-content:center;min-height:100vh}}
.card{{border:1px solid {color};border-radius:8px;padding:40px 48px;text-align:center;max-width:420px}}
h1{{color:{color};font-size:18px;letter-spacing:1px;margin-bottom:12px}}
p{{color:#64748b;font-size:12px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>{heading}</h1>
<p>Your decision has been recorded.<br>You can close this tab.</p>
</div></body></html>""")


def _already_used_page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html>
<html><head><title>Athena — Link already used</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Menlo,Monaco,Consolas,monospace;background:#0b1120;color:#e2e8f0;
     display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{border:1px solid #334155;border-radius:8px;padding:40px 48px;text-align:center;max-width:420px}
h1{color:#64748b;font-size:18px;letter-spacing:1px;margin-bottom:12px}
p{color:#475569;font-size:12px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>Already recorded</h1>
<p>This link has already been used or the engagement has ended.</p>
</div></body></html>""", status_code=status.HTTP_410_GONE)


def _dispatch_decision(state: collaboration.CollabState, *, approved: bool) -> None:
    """Release the gate this co-approval was parked on, per its kind. A committee-gate
    Deny releases as a feedback-less redo (a collaborator has no text channel — see
    COLLABORATION.md 'Known deficiencies')."""
    if state.kind == "committee":
        runner.resolve_gate_decision(
            state.run_id,
            action="accept" if approved else "redo",
            suggestion=None,
        )
    else:
        runner.resolve_approval(state.run_id, approved=approved)


def _resolve(run_id: str, *, approved: bool) -> HTMLResponse:
    state = collaboration.pop(run_id)
    if state is None:
        _log.warning("collab link for %r: no pending state (already used or unknown)", run_id)
        return _already_used_page()

    try:
        _dispatch_decision(state, approved=approved)
    except KeyError:
        _log.warning("collab link for %r: engagement not found or already resolved", run_id)

    decision = "approve" if approved else "deny"
    _log.info("collaboration (%s) for %r resolved: %s by %s", state.kind, run_id, decision, state.email)

    if approved:
        return _page("Approved", "Approved", "#22c55e")
    return _page("Declined", "Declined", "#ef4444")
