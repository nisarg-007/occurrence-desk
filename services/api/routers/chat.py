"""AI Chatbot router — powered by xAI Grok API.

The assistant answers questions about the occurrence database: report counts,
hazard categories, priority distributions, and individual report details.
It queries the live DB first, builds a compact context snapshot, then asks
Grok to answer the user's question grounded in that data.

If no GROK_API_KEY is configured, the endpoint returns a clear error rather
than silently producing hallucinated answers.
"""

from __future__ import annotations

import json
import datetime as dt
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from services.api.deps import analyst, get_repo
from services.api.problems import ApiProblem
from services.api.security import Principal
from services.common.settings import get_settings

router = APIRouter(tags=["chat"])

_GROK_URL = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "groq/compound"  # Groq's compound model — confirmed available on this account

SYSTEM_PROMPT = """\
You are an aviation safety analyst assistant embedded in Occurrence Desk, an \
internal triage tool for ASRS (Aviation Safety Reporting System) reports.

You have access to a live snapshot of the database included below under \
<database_context>. Use ONLY this data to answer the user's question. \
Do not invent reports, counts, or hazard categories that are not in the context.

If the answer is not in the context, say so clearly and suggest what filter \
or query might help. Be concise — one to three sentences unless detail is \
explicitly requested. Format numbers clearly. Never expose raw SQL or \
internal identifiers beyond report ACN numbers.\
"""


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    context_rows: int


def _build_db_context(repo: Any) -> tuple[str, int]:
    """Query the DB and return a compact JSON snapshot for the prompt."""
    rows = repo.list_reports(cursor=None, page_size=5000)

    # Priority distribution
    from services.api import presentation
    from collections import Counter

    priorities = [repo.priority(r) for r in rows]
    band_counts = Counter(presentation.level(v)[1] for v in priorities)
    hazard_counts = Counter(h["label"] for r in rows for h in r.hazards)
    state_counts = Counter(r.state for r in rows)

    top_hazards = [{"hazard": k, "count": v} for k, v in hazard_counts.most_common(10)]
    top_priority_reports = sorted(
        rows, key=lambda r: repo.priority(r), reverse=True
    )[:5]

    top_reports_summary = [
        {
            "acn": r.acn,
            "synopsis": (r.synopsis or "")[:200],
            "priority": repo.priority(r),
            "state": r.state,
            "hazards": [h["label"] for h in r.hazards],
            "report_date": str(r.report_date) if r.report_date else None,
        }
        for r in top_priority_reports
    ]

    context = {
        "as_of": str(dt.date.today()),
        "total_reports": len(rows),
        "states": dict(state_counts),
        "priority_bands": dict(band_counts),
        "top_hazard_categories": top_hazards,
        "top_5_highest_priority_reports": top_reports_summary,
    }
    return json.dumps(context, indent=2), len(rows)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    p: Principal = Depends(analyst),
    repo=Depends(get_repo),
) -> ChatResponse:
    """Send a message to the Grok AI assistant grounded in live DB data."""
    settings = get_settings()

    if not settings.ai_chat_key:
        raise ApiProblem(
            503,
            "AI chatbot not configured",
            "Set GROK_API_KEY in your .env file to enable the AI assistant.",
        )

    db_context, row_count = _build_db_context(repo)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"<database_context>\n{db_context}\n</database_context>\n\n"
                f"Question: {body.message}"
            ),
        },
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _GROK_URL,
            headers={
                "Authorization": f"Bearer {settings.ai_chat_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _MODEL,
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.2,  # low temp: factual, not creative
            },
        )

    if resp.status_code == 401:
        raise ApiProblem(502, "Groq API auth failed", "Check your AI_CHAT_KEY — it must be a valid Groq API key (gsk_…).")
    if resp.status_code == 429:
        raise ApiProblem(429, "Groq rate limit reached", "Please wait a moment and try again.")
    if resp.status_code >= 400:
        raise ApiProblem(
            502, "Groq API error", f"Upstream returned {resp.status_code}."
        )

    data = resp.json()
    reply = data["choices"][0]["message"]["content"].strip()

    return ChatResponse(reply=reply, context_rows=row_count)
