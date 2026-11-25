"""Natural-language / fuzzy find (PRD-02 section 2.2): case-insensitive
substring plus difflib SequenceMatcher >= 0.6 across label_code,
part_number, item_name, po_number. KYC1: prefix stripped at the boundary.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from fastapi import APIRouter
from sqlmodel import select

from app.db import SessionDep
from app.main import envelope
from app.models import Carton, Shelf

router = APIRouter(prefix="/api", tags=["find"])

FUZZY_THRESHOLD = 0.6


def score(query: str, carton: Carton) -> float:
    q = query.strip().lower()
    best = 0.0
    for field in (carton.label_code, carton.part_number, carton.item_name, carton.po_number):
        value = field.lower()
        if q in value:
            return 1.0
        best = max(best, SequenceMatcher(None, q, value).ratio())
        for token in value.replace("-", " ").split():
            best = max(best, SequenceMatcher(None, q, token).ratio())
    return best


@router.get("/find")
def find(q: str, session: SessionDep):
    query = q.upper().removeprefix("KYC1:") if q.upper().startswith("KYC1:") else q
    scored = []
    for carton in session.exec(select(Carton)).all():
        s = score(query, carton)
        if s >= FUZZY_THRESHOLD:
            shelf = session.get(Shelf, carton.dest_shelf_id)
            scored.append(
                (
                    s,
                    {
                        "label_code": carton.label_code,
                        "item_name": carton.item_name,
                        "part_number": carton.part_number,
                        "po_number": carton.po_number,
                        "status": carton.status,
                        "dest_shelf": shelf.code if shelf else None,
                        "dest_level": carton.dest_level,
                        "last_seen_level": carton.last_seen_level,
                    },
                )
            )
    scored.sort(key=lambda pair: pair[0], reverse=True)
    matches = [item for _, item in scored]
    best = scored[0][0] if scored else 0.0
    return envelope(
        answer={"query": q, "matches": matches},
        confidence=best,
        sources=[f"carton:{m['label_code']}" for m in matches],
        needs_human_review=not matches,
        note="" if matches else "no match at or above 0.6 similarity",
    )
