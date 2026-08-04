"""Unit tests for the collaboration inbound-reply helpers.

Covers alias extraction, per-run recipient parsing, Svix signature verification,
and quoted-reply-safe approve/deny parsing. The module reads its config at import
time, so the reply-domain / webhook-secret env vars are set before import via the
autouse fixture below (importlib.reload picks them up)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import os
from types import SimpleNamespace

import pytest

REPLY_DOMAIN = "cool-hedgehog.resend.app"
SECRET_B64 = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
WEBHOOK_SECRET = f"whsec_{SECRET_B64}"


@pytest.fixture(autouse=True)
def collab(monkeypatch):
    monkeypatch.setenv("COLLABORATION_ENABLED", "true")
    monkeypatch.setenv("COLLAB_REPLY_DOMAIN", REPLY_DOMAIN)
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("COLLABORATOR_ALIASES", "matt:matt@example.com")
    import athena.collaboration as c
    importlib.reload(c)
    yield c
    # Restore module to ambient env so other test modules see a clean import.
    importlib.reload(c)


# --- extract_alias ---------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("@matt", "matt"),
    ("matt", "matt"),
    ("@matt do you approve?", "matt"),
    ("please ask @matt now", "matt"),
    ("   ", None),
    ("", None),
])
def test_extract_alias(collab, text, expected):
    assert collab.extract_alias(text) == expected


# --- extract_run_id --------------------------------------------------------

def test_extract_run_id_bare_and_named(collab):
    assert collab.extract_run_id([f"abc-123@{REPLY_DOMAIN}"]) == "abc-123"
    assert collab.extract_run_id([f"Matt <abc-123@{REPLY_DOMAIN}>"]) == "abc-123"


def test_extract_run_id_ignores_other_domains(collab):
    assert collab.extract_run_id(["someone@gmail.com"]) is None
    assert collab.extract_run_id([]) is None


# --- parse_reply_decision --------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("APPROVE", True),
    ("approve", True),
    ("I approve this plan", True),
    ("DENY", False),
    ("I deny this", False),
    ("reject", False),
    ("not sure yet", None),
    ("approve but also deny", None),   # ambiguous → parked
])
def test_parse_reply_decision(collab, text, expected):
    assert collab.parse_reply_decision(text) is expected


def test_parse_reply_ignores_quoted_original(collab):
    # The quoted original says "APPROVE or DENY"; the actual answer is DENY.
    reply = (
        "DENY\n\n"
        "On Mon, Aug 3, 2026 at 4:00 PM Athena <athena@openintel.to> wrote:\n"
        "> reply with APPROVE or DENY to record your decision"
    )
    assert collab.parse_reply_decision(reply) is False


def test_parse_reply_stops_at_quote_marker(collab):
    reply = "approve\n\n> Please reply APPROVE or DENY"
    assert collab.parse_reply_decision(reply) is True


# --- reply_message (collaborator's words shown in chat) ---------------------

def test_reply_message_strips_quoted_original(collab):
    reply = (
        "APPROVE — looks good, nice work\n\n"
        "On Mon, Aug 4, 2026 Athena <athena@openintel.to> wrote:\n"
        "> the engagement summary is attached"
    )
    assert collab.reply_message(reply) == "APPROVE — looks good, nice work"


def test_reply_message_keeps_comment_without_decision(collab):
    reply = "what does this exploit actually touch?\n\n> quoted original"
    assert collab.reply_message(reply) == "what does this exploit actually touch?"
    assert collab.parse_reply_decision(reply) is None  # stays parked, but message shows


# --- verify_webhook_signature ----------------------------------------------

def _sign(body: bytes, svix_id: str, svix_ts: str) -> dict[str, str]:
    key = base64.b64decode(SECRET_B64)
    signed = f"{svix_id}.{svix_ts}.".encode() + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {"svix-id": svix_id, "svix-timestamp": svix_ts, "svix-signature": f"v1,{sig}"}


def test_verify_signature_valid(collab):
    body = b'{"type":"email.received"}'
    headers = _sign(body, "msg_1", "1700000000")
    assert collab.verify_webhook_signature(body, headers) is True


def test_verify_signature_rejects_tampered_body(collab):
    body = b'{"type":"email.received"}'
    headers = _sign(body, "msg_1", "1700000000")
    assert collab.verify_webhook_signature(b'{"x":1}', headers) is False


def test_verify_signature_rejects_missing_headers(collab):
    assert collab.verify_webhook_signature(b"{}", {}) is False


def test_verify_signature_accepts_multiple_versions(collab):
    body = b'{"a":1}'
    headers = _sign(body, "msg_2", "1700000001")
    # Prepend an unrelated version tuple; any match should pass.
    headers["svix-signature"] = "v1,deadbeef " + headers["svix-signature"]
    assert collab.verify_webhook_signature(body, headers) is True


# --- gate-kind dispatch (_dispatch_decision) -------------------------------

def test_dispatch_decision_routes_by_kind(monkeypatch):
    from athena.server.routes import collaboration as routes
    calls: list[tuple] = []
    monkeypatch.setattr(routes.runner, "resolve_gate_decision",
                        lambda run_id, *, action, suggestion: calls.append(("gate", run_id, action, suggestion)))
    monkeypatch.setattr(routes.runner, "resolve_approval",
                        lambda run_id, *, approved: calls.append(("plan", run_id, approved)))

    routes._dispatch_decision(SimpleNamespace(run_id="r1", kind="committee"), approved=True)
    routes._dispatch_decision(SimpleNamespace(run_id="r2", kind="committee"), approved=False)
    routes._dispatch_decision(SimpleNamespace(run_id="r3", kind="plan"), approved=True)

    assert calls == [
        ("gate", "r1", "accept", None),   # committee + approve → advance
        ("gate", "r2", "redo", None),     # committee + deny → feedback-less redo
        ("plan", "r3", True),             # plan → resolve_approval
    ]
