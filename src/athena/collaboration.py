"""Collaboration feature — link-based co-approval at the plan review gate.

Enabled only when COLLABORATION_ENABLED=true in the environment. When disabled
the module is still importable; all public helpers are no-ops or return None.

The collaborator receives an email with two links (approve / deny) pointing
back at this server. No inbound email or MX records required.
"""

from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

_log = logging.getLogger("athena.collaboration")

COLLABORATION_ENABLED = os.environ.get("COLLABORATION_ENABLED", "").strip().lower() == "true"

_RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
_FROM_ADDRESS = "athena@openintel.to"
_BASE_URL = os.environ.get("ATHENA_BASE_URL", "").rstrip("/")


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
) -> None:
    approve_url = f"{_BASE_URL}/webhooks/collab/{run_id}/approve"
    deny_url = f"{_BASE_URL}/webhooks/collab/{run_id}/deny"
    btn = (
        "display:inline-block;padding:10px 24px;border-radius:5px;"
        "font-family:monospace;font-size:13px;font-weight:700;"
        "text-decoration:none;margin:4px"
    )
    html_body = (
        "<p>You have been requested to co-approve an Athena engagement plan.</p>"
        "<h3>Plan</h3>"
        '<pre style="font-family:monospace;white-space:pre-wrap;font-size:12px;'
        'background:#0b1120;color:#e2e8f0;padding:16px;border-radius:6px">'
        f"{html.escape(plan_text)}"
        "</pre>"
        '<p style="margin-top:24px">'
        f'<a href="{approve_url}" style="{btn}background:#14532d;color:#22c55e;border:1px solid #22c55e">✓ Approve</a>'
        f'<a href="{deny_url}" style="{btn}background:#450a0a;color:#ef4444;border:1px solid #ef4444">✗ Deny</a>'
        "</p>"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json={
                "from": _FROM_ADDRESS,
                "to": [to_email],
                "subject": f"[Athena] Co-approval requested (@{alias})",
                "html": html_body,
            },
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}"},
            timeout=10.0,
        )
        resp.raise_for_status()
