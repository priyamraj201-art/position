"""Anthropic Claude provider with a tool loop. Key from ANTHROPIC_API_KEY."""

from __future__ import annotations

import os
from typing import Any

from app.amber.provider import SYSTEM_PROMPT, TOOL_SPECS, AmberProvider, ChatResult, run_tool
from app.amber.tools import AmberStore

DEFAULT_MODEL = "claude-3-5-haiku-latest"
MAX_STEPS = 4
_TYPES = {"string": "string", "boolean": "boolean"}


def _anthropic_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "input_schema": {
                "type": "object",
                "properties": {k: {"type": _TYPES[v]} for k, v in s["properties"].items()},
                "required": s["required"],
            },
        }
        for s in TOOL_SPECS
    ]


class AnthropicProvider(AmberProvider):
    name = "anthropic"

    def __init__(self, store: AmberStore, client: Any = None, model: str | None = None) -> None:
        self._store = store
        self._model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        if client is None:
            import anthropic  # raises ImportError if the SDK is missing

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._client = client

    def chat(self, message: str, confirm: bool = False) -> ChatResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]
        calls: list[dict[str, Any]] = []
        needs_confirmation = False
        reply = ""
        for _ in range(MAX_STEPS):
            resp = self._client.messages.create(
                model=self._model, max_tokens=300, system=SYSTEM_PROMPT,
                tools=_anthropic_tools(), messages=messages)
            reply = "".join(b.text for b in resp.content if b.type == "text")
            uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not uses:
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for use in uses:
                out = run_tool(self._store, use.name, dict(use.input), confirm)
                calls.append({"name": use.name, "args": dict(use.input), "result": out})
                needs_confirmation = needs_confirmation or bool(out.get("needs_confirmation"))
                results.append({"type": "tool_result", "tool_use_id": use.id,
                                "content": str(out)})
            messages.append({"role": "user", "content": results})
        return ChatResult(reply or "Sorry, I could not answer that.", calls, needs_confirmation)
