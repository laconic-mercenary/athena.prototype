"""GET /webhooks/collab/{run_id}/{decision} — link-based co-approval for plan gate.

Registered only when COLLABORATION_ENABLED=true (via app.py). The collaborator
clicks the approve or deny link from the email; this handler releases the plan
review gate and returns a simple confirmation page.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from athena import collaboration
from athena.server import runner

_log = logging.getLogger("athena.server.routes.collaboration")

router = APIRouter()


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
</div></body></html>""", status_code=410)


@router.get("/webhooks/collab/{run_id}/approve")
async def collab_approve(run_id: str) -> HTMLResponse:
    return _resolve(run_id, approved=True)


@router.get("/webhooks/collab/{run_id}/deny")
async def collab_deny(run_id: str) -> HTMLResponse:
    return _resolve(run_id, approved=False)


def _resolve(run_id: str, *, approved: bool) -> HTMLResponse:
    state = collaboration.pop(run_id)
    if state is None:
        _log.warning("collab link for %r: no pending state (already used or unknown)", run_id)
        return _already_used_page()

    try:
        runner.resolve_approval(run_id, approved=approved)
    except KeyError:
        _log.warning("collab link for %r: engagement not found or already resolved", run_id)

    decision = "approve" if approved else "deny"
    _log.info("collaboration for %r resolved: %s by %s", run_id, decision, state.email)

    if approved:
        return _page("Plan approved", "Plan approved", "#22c55e")
    return _page("Plan denied", "Plan denied", "#ef4444")
