"""POST /engagements/{run_id}/report-chat — post-engagement debrief Q&A.

Reads completed artifacts from the engagement's artifact directory and
answers operator questions about the engagement findings.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from athena.model_backend import make_backend
from athena.server import runner

router = APIRouter(prefix="/engagements")

_ARTIFACTS_ROOT = Path("artifacts")
_REPORT_CHAT_MODEL = os.environ.get("REPORT_CHAT_MODEL", "claude-haiku-4-5-20251001")
_REPORT_CHAT_PROVIDER = os.environ.get("REPORT_CHAT_PROVIDER", "anthropic")
_MAX_MESSAGE_LEN = 2000

_SYSTEM = """\
You are an AI assistant helping an operator debrief a completed engagement.
Answer questions about the findings and artifacts accurately and concisely.
Respond based only on the documents provided. Be direct.\
"""

# Per-run conversation history: {run_id: [{"q": ..., "a": ...}]}
_history: dict[str, list[dict[str, str]]] = {}


class ReportChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_LEN)


class ReportChatResponse(BaseModel):
    reply: str


@router.post("/{run_id}/report-chat", response_model=ReportChatResponse)
async def report_chat(run_id: str, body: ReportChatRequest) -> ReportChatResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

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
        raise HTTPException(status_code=404, detail="No artifacts found for this engagement")

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
