"""Regex intent router. No network, no API key."""

from __future__ import annotations

import re
from typing import Any

from app.amber.provider import AmberProvider, ChatResult, run_tool
from app.amber.tools import AmberStore

_CODE = r"(?:KYC1:)?[A-Z0-9]{6}"
_DEL = r"DEL-\d+"
_IT = re.compile(
    r"^(?:please\s+)?(?:light|show|blink)(?: it| that| this)?(?: up)?[?.!]*$", re.IGNORECASE
)
_LIGHT = re.compile(
    r"^(?:please\s+)?(?:light up|blink|show(?: me)?)\s+(.+?)[?.!]*$", re.IGNORECASE
)
_GOES = re.compile(rf"where does\s+({_CODE})\s+go", re.IGNORECASE)
_STATUS = re.compile(rf"status of\s+({_DEL})", re.IGNORECASE)
_DAMAGED = re.compile(rf"^({_CODE})\s+is\s+damaged(?:[:,.]?\s*(.*))?$", re.IGNORECASE)
_ALERTS = re.compile(r"open alerts|any alerts|what alerts", re.IGNORECASE)
_FIND = re.compile(r"^(?:where(?:'s| is| are)|find)\s+(.+?)[?.!]*$", re.IGNORECASE)


class OfflineAmberProvider(AmberProvider):
    name = "offline"

    def __init__(self, store: AmberStore) -> None:
        self._store = store
        self._last: str | None = None  # label code of the last find, for "light it up"

    def _call(self, calls: list[dict[str, Any]], name: str, args: dict[str, Any],
              confirm: bool) -> dict[str, Any]:
        result = run_tool(self._store, name, args, confirm)
        calls.append({"name": name, "args": args, "result": result})
        return result

    def chat(self, message: str, confirm: bool = False) -> ChatResult:
        text = message.strip()
        calls: list[dict[str, Any]] = []
        if m := _GOES.search(text):
            r = self._call(calls, "where_does_this_go", {"carton_code": m[1]}, confirm)
            if not r["found"]:
                return ChatResult(f"I can't find carton {m[1].upper()}.", calls)
            return ChatResult(f"{r['carton_code']} goes to {r['destination']}.", calls)
        if m := _STATUS.search(text):
            r = self._call(calls, "delivery_status", {"delivery_id": m[1]}, confirm)
            if not r["found"]:
                return ChatResult(f"I can't find delivery {m[1].upper()}.", calls)
            reply = f"{r['delivery_id']}: {r['seen']} of {r['expected']} cartons seen."
            if r["missing_codes"]:
                reply += f" Missing: {', '.join(r['missing_codes'])}."
            return ChatResult(reply, calls)
        if m := _DAMAGED.match(text):
            args = {"carton_code": m[1], "note": (m[2] or "").strip()}
            r = self._call(calls, "report_damage", args, confirm)
            if not r.get("found", True):
                return ChatResult(f"I can't find carton {m[1].upper()}.", calls)
            if r.get("needs_confirmation"):
                return ChatResult(r["prompt"], calls, needs_confirmation=True)
            return ChatResult(f"Marked {r['carton_code']} as damaged.", calls)
        if _ALERTS.search(text):
            r = self._call(calls, "list_open_alerts", {}, confirm)
            if r["count"] == 0:
                return ChatResult("No open alerts.", calls)
            return ChatResult(f"{r['count']} open: " + "; ".join(a["message"] for a in r["alerts"]),
                              calls)
        if _IT.match(text) and self._last:
            return self._find(calls, self._last, True, confirm)
        if m := _LIGHT.match(text):
            return self._find(calls, m[1], True, confirm)
        if m := _FIND.match(text):
            return self._find(calls, m[1], False, confirm)
        return ChatResult("Try: where is <item>, light up <item>, status of DEL-2211, "
                          "or open alerts.", calls)

    def _find(self, calls: list[dict[str, Any]], query: str, locate: bool,
              confirm: bool) -> ChatResult:
        r = self._call(calls, "find_carton", {"query": query, "auto_locate": locate}, confirm)
        if not r["matches"]:
            return ChatResult(f"I found nothing matching {query}.", calls)
        top = r["matches"][0]
        self._last = top["label_code"]
        where = top.get("last_seen", f"not seen yet, belongs at {top['belongs_at']}")
        reply = f"{top['item_name']} ({top['label_code']}) is at {where}."
        if len(r["matches"]) > 1:
            reply += f" {len(r['matches']) - 1} more match."
        if locate:
            reply += " Shelf light is blinking."
        return ChatResult(reply, calls)
