"""POST /engagements/{run_id}/report-chat — post-engagement debrief Q&A.

Reads completed artifacts from the engagement's artifact directory and
answers operator questions about the engagement findings.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from athena import env_vars
from athena.model_backend import make_backend
from athena.server import limits, runner

###############
# CONSTS / GLOBALS #
###############

router = APIRouter(prefix="/engagements")

_ARTIFACTS_ROOT = Path("artifacts")
_REPORT_CHAT_MODEL: str | None = os.environ.get(env_vars.SRV_REPORT_CHAT_MODEL)
_REPORT_CHAT_PROVIDER: str | None = os.environ.get(env_vars.SRV_REPORT_CHAT_PROVIDER)

_SYSTEM = """\
You are an AI assistant helping an operator debrief a completed engagement.
Answer questions about the findings and artifacts accurately and concisely.
Respond based only on the documents provided. Be direct.\
"""

# Per-run conversation history: {run_id: [{"q": ..., "a": ...}]}
_history: dict[str, list[dict[str, str]]] = {}


###############
# CUSTOM TYPES #
###############

class ReportChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=limits.MAX_MESSAGE_LEN)


class ReportChatResponse(BaseModel):
    reply: str


###############
# FUNCTIONS #
###############

@router.post("/{run_id}/report-chat", response_model=ReportChatResponse)
async def report_chat(run_id: str, body: ReportChatRequest) -> ReportChatResponse:
    if not _REPORT_CHAT_MODEL:
        raise RuntimeError(f"{env_vars.SRV_REPORT_CHAT_MODEL} environment variable is not set")
    if not _REPORT_CHAT_PROVIDER:
        raise RuntimeError(f"{env_vars.SRV_REPORT_CHAT_PROVIDER} environment variable is not set")
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")

    run_dir = _ARTIFACTS_ROOT / run_id
    docs: dict[str, str] = {}
    if run_dir.is_dir():
        for path in sorted(run_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
                docs[path.stem] = json.dumps(raw, indent=2)
            except Exception:
                docs[path.stem] = path.read_text()

    if not docs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No artifacts found for this engagement"
        )

    history = _history.get(run_id, [])
    msg = body.message.strip()

    parts: list[str] = []
    for label, text in docs.items():
        parts.append(f"== {label.upper()} ==\n{text}")
    if history:
        exchange_text = "\n".join(f"Operator: {h['q']}\nYou: {h['a']}" for h in history)
        parts.append(f"== PRIOR CONVERSATION ==\n{exchange_text}")
    parts.append(f"Operator: {msg}")
    initial_message = "\n\n".join(parts)

    def _call_model() -> str:
        backend = make_backend(_REPORT_CHAT_PROVIDER, None)
        backend.begin(system=_SYSTEM, initial_message=initial_message)
        response = backend.complete(model=_REPORT_CHAT_MODEL, tools=None, max_tokens=1024)
        return response.text or ""

    reply = await asyncio.to_thread(_call_model)

    _history.setdefault(run_id, []).append({"q": msg, "a": reply})
    return ReportChatResponse(reply=reply)
