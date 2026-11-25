"""Gemini provider (google-genai). Key from GEMINI_API_KEY."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from app.amber.provider import SYSTEM_PROMPT, AmberProvider, ChatResult, run_tool
from app.amber.tools import AmberStore

DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider(AmberProvider):
    name = "gemini"

    def __init__(self, store: AmberStore, client: Any = None, model: str | None = None) -> None:
        self._store = store
        self._model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        if client is None:
            from google import genai  # raises ImportError if the SDK is missing

            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self._client = client

    def _functions(self, calls: list[dict[str, Any]], confirm: bool) -> list[Callable[..., Any]]:
        """Plain functions the SDK turns into tool declarations. `confirm` is not a parameter."""

        def record(name: str, args: dict[str, Any]) -> dict[str, Any]:
            out = run_tool(self._store, name, args, confirm)
            calls.append({"name": name, "args": args, "result": out})
            return out

        def find_carton(query: str, auto_locate: bool = False) -> dict[str, Any]:
            """Find cartons by code, part number, name or PO. auto_locate lights the shelf."""
            return record("find_carton", {"query": query, "auto_locate": auto_locate})

        def where_does_this_go(carton_code: str) -> dict[str, Any]:
            """Destination floor and shelf of a carton."""
            return record("where_does_this_go", {"carton_code": carton_code})

        def delivery_status(delivery_id: str) -> dict[str, Any]:
            """Expected, seen and missing cartons of a delivery."""
            return record("delivery_status", {"delivery_id": delivery_id})

        def report_damage(carton_code: str, note: str = "") -> dict[str, Any]:
            """Mark a carton damaged. The user is asked to confirm first."""
            return record("report_damage", {"carton_code": carton_code, "note": note})

        def list_open_alerts() -> dict[str, Any]:
            """Summary of open alerts."""
            return record("list_open_alerts", {})

        return [find_carton, where_does_this_go, delivery_status, report_damage, list_open_alerts]

    def chat(self, message: str, confirm: bool = False) -> ChatResult:
        from google.genai import types

        calls: list[dict[str, Any]] = []
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, tools=self._functions(calls, confirm))
        resp = self._client.models.generate_content(
            model=self._model, contents=message, config=config)
        needs = any(c["result"].get("needs_confirmation") for c in calls)
        return ChatResult(resp.text or "Sorry, I could not answer that.", calls, needs)
