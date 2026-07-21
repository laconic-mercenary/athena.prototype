"""POST /engagements/{run_id}/plan-review — plan Q&A and approval gate."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from athena.model_backend import make_backend
from athena.server import runner

router = APIRouter(prefix="/engagements")

_MAX_MESSAGE_LEN = 2000

_SYSTEM = """\
You are an AI assistant helping an operator review a penetration test plan before approving execution.
Your job is to answer questions about the reconnaissance findings and proposed plan accurately and concisely.
Respond based only on the content provided. Be direct. Do not use markdown formatting in replies.
The operator can end the review by typing exactly "approve" or "reject".\
"""


class PlanReviewRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_LEN)


class PlanReviewResponse(BaseModel):
    reply: str | None = None
    action: str | None = None  # "approved" | "rejected"


@router.post("/{run_id}/plan-review", response_model=PlanReviewResponse)
async def plan_review(run_id: str, body: PlanReviewRequest, request: Request) -> PlanReviewResponse:
    ctx = runner.get_context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not ctx.awaiting_approval:
        raise HTTPException(status_code=409, detail="Pipeline is not currently awaiting approval")

    msg = body.message.strip()

    # Approve / reject — deterministic keyword check, no model call needed.
    if msg.lower() == "approve":
        try:
            runner.resolve_approval(run_id, approved=True)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return PlanReviewResponse(action="approved")

    if msg.lower() == "reject":
        try:
            runner.resolve_approval(run_id, approved=False)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return PlanReviewResponse(action="rejected")

    # Q&A — run the blocking model call in a thread so we don't stall the event loop.
    config = request.app.state.config
    model = config.plan_review.model

    run_dir = config.artifacts_dir / run_id
    recon_text = (run_dir / "recon.md").read_text() if (run_dir / "recon.md").exists() else ""
    plan_text  = (run_dir / "plan.md").read_text()  if (run_dir / "plan.md").exists()  else ""

    history = runner.get_plan_review_history(run_id)

    # Build a single user message that includes both documents and any prior conversation.
    parts: list[str] = []
    if recon_text:
        parts.append(f"== RECONNAISSANCE FINDINGS ==\n{recon_text}")
    if plan_text:
        parts.append(f"== PROPOSED RETRIEVAL PLAN ==\n{plan_text}")
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
    runner.add_plan_review_exchange(run_id, msg, reply)

    return PlanReviewResponse(reply=reply)
