"""Confidence, sources and needs-human-review rules for the MCP adapter.

Rules (documented here, tested in tests/test_mcp_server.py):

find_carton
  - no match: confidence 0.0, needs_human_review true.
  - the query is contained in a label code, part number, name or PO: score 1.0, confidence 1.0.
  - fuzzy score >= 0.90: high, confidence = score.
  - 0.75 <= score < 0.90: medium, confidence = score.
  - 0.60 <= score < 0.75: low, confidence = score, needs_human_review true.
  - top two matches for different items within 0.05 of each other: ambiguous,
    needs_human_review true (a shelf light must not blink for a guess).
where_does_this_go
  - carton found in the database: 1.0. Not found: 0.0 and needs_human_review true.
delivery_status
  - delivery found: 1.0, needs_human_review true when cartons are missing (short delivery).
  - not found: 0.0 and needs_human_review true.
report_damage
  - never records through MCP. It always returns needs_confirmation and needs_human_review true;
    a person confirms in the app (`/api/amber/chat` with confirm).
resolve_alert (optional)
  - needs a non-empty human note. Empty note or unknown alert: 0.0 and needs_human_review true.
list_open_alerts, list_cartons
  - database read: 1.0, needs_human_review false.
Unknown or malformed carton codes are never stored or guessed: the answer says not found and
needs_human_review is true.
sources are database references like "carton:KYC1:BV2401", "delivery:DEL-2211", "alert:12".
"""

from __future__ import annotations

from typing import Any

HIGH = 0.90
MEDIUM = 0.75
AMBIGUOUS_GAP = 0.05


def envelope(answer: Any, confidence: float, sources: list[str], review: bool,
             note: str | None = None) -> dict[str, Any]:
    return {"answer": answer, "confidence": round(confidence, 2), "sources": sources,
            "needs_human_review": review, "note": note}


def find_confidence(result: dict[str, Any]) -> tuple[float, bool, str | None]:
    """Return (confidence, needs_human_review, note) for a find_carton result."""
    matches = result["matches"]
    if not matches:
        return 0.0, True, "No carton matched. Ask a person."
    top = matches[0]["score"]
    if top >= 1.0:
        confidence, review, note = 1.0, False, None
    elif top >= MEDIUM:
        confidence, review, note = top, False, None
    else:
        confidence, review, note = top, True, "Weak match. Check before acting."
    if len(matches) > 1 and top - matches[1]["score"] <= AMBIGUOUS_GAP:
        first, second = matches[0], matches[1]
        if first["item_name"] != second["item_name"]:
            return confidence, True, "Several different items match. Ask which one."
    return confidence, review, note
