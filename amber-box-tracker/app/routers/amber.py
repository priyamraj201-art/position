"""Amber chat endpoint (PRD-02 section 2.2). Track 4 owns the provider;
until app/amber/provider.py lands this returns 503 with the envelope."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import SessionDep, get_engine
from app.main import envelope

router = APIRouter(prefix="/api/amber", tags=["amber"])


class ChatBody(BaseModel):
    message: str
    confirm: bool | None = None


@router.post("/chat")
def chat(body: ChatBody, session: SessionDep):
    try:
        from app.amber.provider import get_provider
    except ImportError:
        raise HTTPException(
            503,
            envelope(
                answer=None,
                confidence=0.0,
                sources=[],
                needs_human_review=True,
                note="amber provider not yet integrated (Track 4)",
            ),
        )
    provider = get_provider(engine=get_engine())
    return provider.chat(body.message, confirm=bool(body.confirm))
