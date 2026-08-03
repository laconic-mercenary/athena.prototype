"""Collaboration feature — link-based co-approval at the plan review gate.

Enabled only when COLLABORATION_ENABLED=true in the environment. When disabled
the module is still importable; all public helpers are no-ops or return None.

The collaborator receives an email with two links (approve / deny) pointing
back at this server. No inbound email or MX records required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr

import httpx

_log = logging.getLogger("athena.collaboration")

COLLABORATION_ENABLED = os.environ.get("COLLABORATION_ENABLED", "").strip().lower() == "true"

_RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
_FROM_ADDRESS = "athena@openintel.to"
_BASE_URL = os.environ.get("ATHENA_BASE_URL", "").rstrip("/")

# Inbound reply-in-email support. Collaborators reply to a per-run address
# (<run_id>@<REPLY_DOMAIN>); Resend receives it and POSTs an email.received
# webhook to us. REPLY_DOMAIN is the Resend-managed receiving domain (e.g.
# "cool-hedgehog.resend.app") — no DNS/MX to configure. When unset we fall back
# to the click-link flow (no reply_to header is added).
_REPLY_DOMAIN = os.environ.get("COLLAB_REPLY_DOMAIN", "").strip().lstrip("@")
# Svix-style signing secret shown when the email.received webhook is created
# ("whsec_..."). Used to verify inbound webhook authenticity.
_WEBHOOK_SECRET = os.environ.get("RESEND_WEBHOOK_SECRET", "").strip()


def _parse_aliases() -> dict[str, str]:
    raw = os.environ.get("COLLABORATOR_ALIASES", "")
    result: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        alias, email = pair.split(":", 1)
        alias = alias.strip().lstrip("@")
        email = email.strip()
        if alias and email:
            result[alias] = email
    return result


_ALIASES: dict[str, str] = _parse_aliases() if COLLABORATION_ENABLED else {}


@dataclass
class CollabState:
    run_id: str
    alias: str
    email: str
    sent_at: datetime


_pending: dict[str, CollabState] = {}


# Alias chars: word-ish, matching how COLLABORATOR_ALIASES keys are written.
_ALIAS_RE = re.compile(r"@?([A-Za-z0-9_.\-]+)")


def extract_alias(text: str | None) -> str | None:
    """Pull the collaborator alias out of a free-text co-approval field.

    The field is free text — an @-token anywhere in it names the collaborator
    (e.g. "@matt do you approve?"). Prefer the first explicit @-token; fall back
    to the first word so a bare "matt" still resolves. So "@matt do you approve?",
    "@matt" and "matt" all resolve to "matt". Returns None for empty/blank input.
    """
    if not text or not text.strip():
        return None
    at = re.search(r"@([A-Za-z0-9_.\-]+)", text)
    if at:
        return at.group(1)
    first = _ALIAS_RE.match(text.strip())
    return first.group(1) if first else None


def resolve_alias(alias: str) -> str | None:
    return _ALIASES.get(alias.lstrip("@"))


def register(run_id: str, alias: str, email: str) -> CollabState:
    state = CollabState(
        run_id=run_id,
        alias=alias,
        email=email,
        sent_at=datetime.now(timezone.utc),
    )
    _pending[run_id] = state
    return state


def pop(run_id: str) -> CollabState | None:
    return _pending.pop(run_id, None)


async def send_approval_request(
    run_id: str,
    alias: str,
    to_email: str,
    plan_text: str,
    note: str = "",
) -> None:
    approve_url = f"{_BASE_URL}/webhooks/collab/{run_id}/approve"
    deny_url = f"{_BASE_URL}/webhooks/collab/{run_id}/deny"
    # The operator's own message (the text they @-mentioned the collaborator in) is
    # the most important context — it often says WHY approval is being sought. Render
    # it up top in a highlighted quote block so it can't be missed.
    note = (note or "").strip()
    note_block = (
        '<div style="margin:16px 0;padding:14px 16px;border-left:4px solid #3b82f6;'
        'background:#f1f5f9;border-radius:4px">'
        '<div style="font-size:12px;font-weight:700;color:#334155;'
        'text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px">'
        "Message from the operator"
        "</div>"
        f'<div style="font-size:15px;color:#0f172a;white-space:pre-wrap">'
        f"{html.escape(note)}</div>"
        "</div>"
    ) if note else ""
    # Plain visible links, not styled <a> "buttons": some email clients strip the
    # button styling (or the whole element) and the recipient is left with nothing to
    # click. Showing the full URL as the link text means it stays usable even if the
    # anchor is stripped — the operator can copy/paste it. The plan itself rides along
    # as a plain-text attachment (a JSON blob inline is unreadable in an email).
    html_body = (
        "<p>You have been requested to co-approve an Athena engagement plan.</p>"
        f"{note_block}"
        "<p>The engagement briefing is attached as <strong>plan-briefing.txt</strong>. "
        "Review it, then use one of the links below.</p>"
        f'<p style="margin:18px 0">✓ <strong>Approve</strong>:<br>'
        f'<a href="{approve_url}">{html.escape(approve_url)}</a></p>'
        f'<p style="margin:18px 0">✗ <strong>Deny</strong>:<br>'
        f'<a href="{deny_url}">{html.escape(deny_url)}</a></p>'
        '<p style="color:#64748b;font-size:12px">If a link is not clickable, copy the '
        "full URL into your browser.</p>"
    )
    attachment = base64.b64encode(plan_text.encode("utf-8")).decode("ascii")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json={
                "from": _FROM_ADDRESS,
                "to": [to_email],
                "subject": f"[Athena] Co-approval requested (@{alias})",
                "html": html_body,
                "attachments": [
                    {"filename": "plan-briefing.txt", "content": attachment}
                ],
            },
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}"},
            timeout=10.0,
        )
        resp.raise_for_status()
