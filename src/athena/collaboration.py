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
    # Which gate this co-approval releases: "plan" → runner.resolve_approval;
    # "committee" → runner.resolve_gate_decision(action="accept"|"redo"). The inbound
    # link/email handlers dispatch on this so one mechanism serves both gates.
    kind: str
    # Committee being gated (committee kind) so a collaborator's reply routes to that
    # leader's chat. None for the plan gate, which routes to the orchestrator chat.
    committee: str | None


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


def register(run_id: str, alias: str, email: str, kind: str, committee: str | None) -> CollabState:
    state = CollabState(
        run_id=run_id,
        alias=alias,
        email=email,
        sent_at=datetime.now(timezone.utc),
        kind=kind,
        committee=committee,
    )
    _pending[run_id] = state
    return state


def get(run_id: str) -> CollabState | None:
    """Peek at the pending state without consuming it — used to surface a collaborator's
    message even when their reply carries no clear decision (the gate stays parked)."""
    return _pending.get(run_id)


def pop(run_id: str) -> CollabState | None:
    return _pending.pop(run_id, None)


async def send_approval_request(
    run_id: str,
    alias: str,
    to_email: str,
    plan_text: str,
    note: str,
    context_noun: str,
    attachment_name: str,
) -> None:
    note = (note or "").strip()
    note_block = (
        '<div style="margin:16px 0;padding:14px 16px;border-left:4px solid #3b82f6;'
        'background:#f1f5f9;border-radius:4px">'
        '<div style="font-size:12px;font-weight:700;color:#334155;'
        'text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px">'
        "Message"
        "</div>"
        f'<div style="font-size:15px;color:#0f172a;white-space:pre-wrap">'
        f"{html.escape(note)}</div>"
        "</div>"
    ) if note else ""
    html_body = (
        f"<p>You have been requested to co-approve an Athena {html.escape(context_noun)}.</p>"
        f"{note_block}"
        f"<p>The engagement summary is attached as <strong>{html.escape(attachment_name)}</strong>.</p>"
        '<p style="margin:18px 0;font-size:15px">To record your decision, simply '
        '<strong>reply to this email</strong> with the word '
        '<strong>APPROVE</strong> or <strong>DENY</strong>.</p>'
    )
    attachment = base64.b64encode(plan_text.encode("utf-8")).decode("ascii")
    payload = {
        "from": _FROM_ADDRESS,
        "to": [to_email],
        "subject": f"[Athena] Co-approval requested (@{alias})",
        "html": html_body,
        "attachments": [
            {"filename": attachment_name, "content": attachment}
        ],
    }
    if _REPLY_DOMAIN:
        payload["reply_to"] = f"{run_id}@{_REPLY_DOMAIN}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}"},
            timeout=10.0,
        )
        resp.raise_for_status()


async def send_collaborator_message(run_id: str, alias: str, to_email: str, text: str) -> None:
    """Send a plain-text follow-up to a collaborator mid-thread (no attachment).

    Used while a committee gate is parked on a collaborator: the operator keeps the
    conversation going by email until the collaborator replies APPROVE. Reuses the same
    per-run reply address so the collaborator's replies still correlate to this engagement.
    """
    text = (text or "").strip()
    html_body = (
        f'<div style="font-size:15px;color:#0f172a;white-space:pre-wrap">{html.escape(text)}</div>'
        '<p style="margin:18px 0;font-size:14px;color:#475569">Reply with '
        '<strong>APPROVE</strong> when you are ready to approve; otherwise just reply with your '
        "comments and we'll continue.</p>"
    )
    payload = {
        "from": _FROM_ADDRESS,
        "to": [to_email],
        "subject": f"[Athena] Co-approval discussion (@{alias})",
        "html": html_body,
    }
    if _REPLY_DOMAIN:
        payload["reply_to"] = f"{run_id}@{_REPLY_DOMAIN}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}"},
            timeout=10.0,
        )
        resp.raise_for_status()


# --- Inbound reply handling (Resend email.received webhook) -----------------

def webhook_secret_configured() -> bool:
    """Whether a webhook signing secret is set. When False, verify_webhook_signature can only
    return False — every inbound reply is rejected. A quick diagnostic for 'no replies arrive'."""
    return bool(_WEBHOOK_SECRET)


def reply_domain_configured() -> str:
    """The configured inbound reply domain (empty string if unset). Without it, outbound emails
    carry no Reply-To, so replies bounce to the From address (which has no inbound webhook)."""
    return _REPLY_DOMAIN


def verify_webhook_signature(body: bytes, headers: dict[str, str]) -> bool:
    """Verify a Resend (Svix) webhook signature over the raw request body.

    Svix signs `{svix-id}.{svix-timestamp}.{body}` with HMAC-SHA256 using the
    secret (the part after "whsec_", base64-decoded). The svix-signature header
    is a space-separated list of `v1,<base64sig>` entries; a match on any one
    passes. Returns False on any missing header or malformed secret. If no
    secret is configured we cannot verify — treat as unverified (False) so the
    caller can decide; callers should refuse to act on unverified webhooks.
    """
    if not _WEBHOOK_SECRET:
        _log.warning("verify: no RESEND_WEBHOOK_SECRET configured")
        return False
    # Header names arrive lower-cased from Starlette; be tolerant anyway. Resend uses
    # the "svix-*" names; the Standard Webhooks spec (which Svix also emits) uses the
    # unbranded "webhook-*" names. Accept either so a rename doesn't silently 401.
    lower = {k.lower(): v for k, v in headers.items()}
    svix_id = lower.get("svix-id") or lower.get("webhook-id")
    svix_ts = lower.get("svix-timestamp") or lower.get("webhook-timestamp")
    svix_sig = lower.get("svix-signature") or lower.get("webhook-signature")
    if not (svix_id and svix_ts and svix_sig):
        _log.warning(
            "verify: missing signing headers (id=%s ts=%s sig=%s); headers seen=%s",
            bool(svix_id), bool(svix_ts), bool(svix_sig), sorted(lower.keys()),
        )
        return False
    secret = _WEBHOOK_SECRET
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    try:
        key = base64.b64decode(secret)
    except Exception:
        _log.warning("verify: secret is not valid base64 after the whsec_ prefix")
        return False
    signed = f"{svix_id}.{svix_ts}.".encode("utf-8") + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    # svix-signature: "v1,<sig> v1,<sig2> ...". Take the part after the version comma; if a
    # provider sends a bare signature with no "v1," prefix, fall back to the whole token.
    candidates = []
    for part in svix_sig.split():
        _, comma, sig = part.partition(",")
        candidates.append(sig if comma else part)
    for sig in candidates:
        if sig and hmac.compare_digest(sig, expected):
            return True
    # Signature mismatch — the headers are present but the HMAC didn't match. Log enough to tell
    # apart "wrong secret" from "body was altered in transit" (a proxy re-encoding the JSON is a
    # classic cause) without leaking anything sensitive: lengths + short digest prefixes only.
    _log.warning(
        "verify: signature mismatch (body_len=%d, key_len=%d, expected=%s…, received=%s)",
        len(body), len(key), expected[:12], [c[:12] for c in candidates],
    )
    return False


def extract_run_id(recipients: list[str]) -> str | None:
    """Pull the engagement run_id from the reply's recipient list.

    Replies are addressed to `<run_id>@<REPLY_DOMAIN>`; the local-part is the
    run_id. Matches only the configured reply domain so unrelated To/Cc lines are
    ignored. Handles both "addr@dom" and "Name <addr@dom>" forms.
    """
    if not _REPLY_DOMAIN:
        return None
    for raw in recipients or []:
        # Resend may deliver recipients as plain strings ("a@b", "Name <a@b>") or as objects
        # ({"address": "a@b"} / {"email": "a@b"}). Normalise both to a string before parsing —
        # otherwise a dict silently yields no address and the reply looks uncorrelated.
        if isinstance(raw, dict):
            raw = raw.get("address") or raw.get("email") or ""
        if not isinstance(raw, str):
            continue
        addr = parseaddr(raw)[1]
        local, _, domain = addr.partition("@")
        if local and domain.lower() == _REPLY_DOMAIN.lower():
            return local.strip()
    return None


async def fetch_received_email_text(email_id: str) -> str:
    """Fetch the full inbound email body from Resend.

    The email.received webhook carries metadata only — the body is retrieved
    separately via GET /emails/receiving/{id}. Prefers the plain-text part;
    falls back to a crude tag-strip of the HTML part when text is null.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.resend.com/emails/receiving/{email_id}",
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    text = data.get("text")
    if text:
        return text
    html_part = data.get("html") or ""
    return re.sub(r"<[^>]+>", " ", html_part)


# APPROVE / DENY as standalone words (case-insensitive). Anchored to word
# boundaries so "disapprove" or a quoted "...approve the plan..." in the original
# doesn't false-match; we scan only the top reply portion (see parse_reply_decision).
_APPROVE_RE = re.compile(r"\bapprove\b", re.IGNORECASE)
_DENY_RE = re.compile(r"\b(deny|reject)\b", re.IGNORECASE)


def parse_reply_decision(text: str) -> bool | None:
    """Return True (approve), False (deny), or None (no clear keyword).

    Only the text ABOVE the first quoted-original marker is considered, so the
    approve/deny wording in the quoted original email can't be mistaken for the
    collaborator's answer. If both keywords appear in that region, it's ambiguous
    → None (the gate stays parked; the operator can fall back to the links).
    """
    top = _reply_top(text)
    has_approve = bool(_APPROVE_RE.search(top))
    has_deny = bool(_DENY_RE.search(top))
    if has_approve and not has_deny:
        return True
    if has_deny and not has_approve:
        return False
    return None


# Lines that typically introduce the quoted original in a reply. Everything from
# the first such marker onward is dropped before keyword scanning.
_QUOTE_MARKERS = (
    re.compile(r"^\s*On .+ wrote:\s*$", re.IGNORECASE),   # Gmail/Apple
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),  # Outlook
    re.compile(r"^\s*_{5,}\s*$"),                          # Outlook underscore rule
    re.compile(r"^\s*From:\s.+", re.IGNORECASE),          # forwarded header block
)


def _reply_top(text: str) -> str:
    lines = (text or "").splitlines()
    kept: list[str] = []
    for line in lines:
        if line.lstrip().startswith(">"):
            break
        if any(m.match(line) for m in _QUOTE_MARKERS):
            break
        kept.append(line)
    return "\n".join(kept)


# Cap the collaborator message we surface in the UI so a giant reply (or a mail
# client that fails to quote its original) can't flood the chat.
_REPLY_MESSAGE_MAX_LEN = 1000


def reply_message(text: str) -> str:
    """The collaborator's own words to show in the chat — the reply above any quoted
    original, trimmed. Empty string when the reply is only quoted text / blank."""
    return _reply_top(text).strip()[:_REPLY_MESSAGE_MAX_LEN]
