"""POST /engagements/{run_id}/report-chat — post-engagement report debrief Q&A."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from athena.model_backend import make_backend
from athena.server import runner

router = APIRouter(prefix="/engagements")

_MAX_MESSAGE_LEN = 2000

_SYSTEM = """\
You are an AI assistant helping an operator debrief a completed penetration test engagement.
Answer questions about the reconnaissance findings, the retrieval plan, the data collected, \
and the final risk assessment accurately and concisely.
Respond based only on the documents provided. Be direct. Do not use markdown formatting in replies.\
"""


class ReportChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_LEN)


class ReportChatResponse(BaseModel):
    reply: str


@router.post("/{run_id}/report-chat", response_model=ReportChatResponse)
async def report_chat(run_id: str, body: ReportChatRequest, request: Request) -> ReportChatResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

    config = request.app.state.config
    model  = config.plan_review.model  # reuse the same model tier

    run_dir = config.artifacts_dir / run_id
    docs: dict[str, str] = {}
    for name in ("recon", "plan", "retrieval", "report"):
        path = run_dir / f"{name}.md"
        if path.exists():
            docs[name] = path.read_text()

    if not docs:
        raise HTTPException(status_code=404, detail="No artifacts found for this engagement")

    history = runner.get_report_chat_history(run_id)
    msg     = body.message.strip()

    parts: list[str] = []
    for label, text in docs.items():
        parts.append(f"== {label.upper()} ==\n{text}")
    if history:
        exchange_text = "\n".join(f"Operator: {h['q']}\nYou: {h['a']}" for h in history)
        parts.append(f"== PRIOR CONVERSATION ==\n{exchange_text}")
    parts.append(f"Operator: {msg}")

    initial_message = "\n\n".join(parts)

    def _call_model() -> str:
        backend = make_backend(config.model.provider, config.model.ollama_base_url)
        backend.begin(system=_SYSTEM, initial_message=initial_message)
        response = backend.complete(model=model, tools=None, max_tokens=1024)
        return response.text or ""

    reply = await asyncio.to_thread(_call_model)
    runner.add_report_chat_exchange(run_id, msg, reply)

    return ReportChatResponse(reply=reply)
