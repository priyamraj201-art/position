"""Amber provider interface, shared tool dispatch and provider selection."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.amber import tools
from app.amber.tools import AmberStore

SYSTEM_PROMPT = (
    "You are Amber, Kaya's site assistant. Answer in 1-2 short spoken sentences. "
    "Always use tools; never invent locations. Floors are 'Floor N', shelves are codes like L2-B2."
)

#: Tools an LLM may call. `confirm` is never exposed: the request's confirm flag is injected.
TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "find_carton", "description": "Find cartons by code, part number, name or PO. "
     "Set auto_locate when the user says show, light or blink.",
     "properties": {"query": "string", "auto_locate": "boolean"}, "required": ["query"]},
    {"name": "where_does_this_go", "description": "Destination floor and shelf of a carton.",
     "properties": {"carton_code": "string"}, "required": ["carton_code"]},
    {"name": "delivery_status", "description": "Expected, seen and missing cartons of a delivery.",
     "properties": {"delivery_id": "string"}, "required": ["delivery_id"]},
    {"name": "report_damage", "description": "Mark a carton damaged (asks the user to confirm).",
     "properties": {"carton_code": "string", "note": "string"}, "required": ["carton_code"]},
    {"name": "list_open_alerts", "description": "Summary of open alerts.",
     "properties": {}, "required": []},
]


@dataclass
class ChatResult:
    reply: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    needs_confirmation: bool = False


def run_tool(store: AmberStore, name: str, args: dict[str, Any], confirm: bool) -> dict[str, Any]:
    """Dispatch one tool call. Unknown tools and bad arguments return an error dict."""
    try:
        if name == "find_carton":
            return tools.find_carton(store, str(args["query"]), bool(args.get("auto_locate")))
        if name == "where_does_this_go":
            return tools.where_does_this_go(store, str(args["carton_code"]))
        if name == "delivery_status":
            return tools.delivery_status(store, str(args["delivery_id"]))
        if name == "report_damage":
            return tools.report_damage(store, str(args["carton_code"]),
                                       str(args.get("note", "")), confirm)
        if name == "list_open_alerts":
            return tools.list_open_alerts(store)
    except KeyError as exc:
        return {"error": f"missing argument {exc}"}
    return {"error": f"unknown tool {name}"}


class AmberProvider(ABC):
    name: str

    @abstractmethod
    def chat(self, message: str, confirm: bool = False) -> ChatResult:
        """Answer one message. confirm=True re-sends a message that needed confirmation."""


def get_provider(store: AmberStore | None = None, *, engine: Any = None) -> AmberProvider:
    """Gemini or Anthropic when a key is set and the SDK works, otherwise offline regex.

    Pass a ready `store`, or an SQLAlchemy `engine` (what the FastAPI router has) to use the app
    database through `SqlAmberStore`.
    """
    from app.amber.offline_provider import OfflineAmberProvider

    if store is None:
        if engine is None:
            raise ValueError("get_provider needs a store or an engine")
        from app.amber.sql_store import SqlAmberStore

        store = SqlAmberStore(engine)

    try:
        if os.getenv("ANTHROPIC_API_KEY"):
            from app.amber.anthropic_provider import AnthropicProvider

            return AnthropicProvider(store)
        if os.getenv("GEMINI_API_KEY"):
            from app.amber.gemini_provider import GeminiProvider

            return GeminiProvider(store)
    except ImportError:
        pass
    return OfflineAmberProvider(store)
