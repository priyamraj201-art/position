"""Thin MCP adapter core (JSON-RPC 2.0, standard library only).

It adds no logic or storage of its own: every tool calls `app.amber.tools` over an `AmberStore`
(the app's SQLite data), then wraps the result in the envelope from `envelope.py`.

Submission transport: `app/amber/mcp_http.py` mounts this inside the FastAPI process, so light
commands and SSE alerts share the app's in-memory queues.
The stdio loop below (`python -m app.amber.mcp_server`) is a DEV CONVENIENCE ONLY. It runs in a
separate process, so lights and live alerts do not reach the running app. Not for the submission.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from app.amber import tools
from app.amber.envelope import envelope, find_confidence
from app.amber.tools import AmberStore

SERVER_NAME = "amber-box-tracker"
SERVER_VERSION = "0.4.0"
_STR = {"type": "string"}


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


TOOLS: list[dict[str, Any]] = [
    {"name": "find_carton", "description": "Find cartons by label code, part number, name or PO. "
     "Set auto_locate to blink the shelf light of the best match.",
     "inputSchema": _schema({"query": _STR, "auto_locate": {"type": "boolean"}}, ["query"])},
    {"name": "where_does_this_go", "description": "Destination floor and shelf of a carton "
     "(label code KYC1:XXXXXX).", "inputSchema": _schema({"carton_code": _STR}, ["carton_code"])},
    {"name": "delivery_status", "description": "Expected, seen and missing cartons of a delivery, "
     "from stored sightings.", "inputSchema": _schema({"delivery_id": _STR}, ["delivery_id"])},
    {"name": "report_damage", "description": "Start a damage report. Never records by itself: a "
     "person confirms in the app.",
     "inputSchema": _schema({"carton_code": _STR, "note": _STR}, ["carton_code"])},
    {"name": "list_open_alerts", "description": "Open alerts: wrong floor, wrong shelf, not "
     "arrived, short delivery, damaged.", "inputSchema": _schema({}, [])},
    {"name": "resolve_alert", "description": "[optional] Close an alert. Needs a note written by "
     "a person.", "inputSchema": _schema({"alert_id": {"type": "integer"}, "note": _STR},
                                         ["alert_id", "note"])},
    {"name": "list_cartons", "description": "[optional] Every carton with status and destination.",
     "inputSchema": _schema({}, [])},
]


class AmberMcpServer:
    def __init__(self, store: AmberStore) -> None:
        self._store = store

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool and return the envelope. Raises KeyError for unknown tool/argument."""
        s = self._store
        if name == "find_carton":
            r = tools.find_carton(s, str(args["query"]), bool(args.get("auto_locate")))
            conf, review, note = find_confidence(r)
            if r.get("locate") and review:
                note = (note or "") + " Shelf light was queued for the best match."
            return envelope(r, conf, [f"carton:{m['label_code']}" for m in r["matches"]],
                            review, note)
        if name == "where_does_this_go":
            r = tools.where_does_this_go(s, str(args["carton_code"]))
            if not r["found"]:
                return envelope(r, 0.0, [], True, "Unknown carton code.")
            return envelope(r, 1.0, [f"carton:{r['carton_code']}"], False)
        if name == "delivery_status":
            r = tools.delivery_status(s, str(args["delivery_id"]))
            if not r["found"]:
                return envelope(r, 0.0, [], True, "Unknown delivery.")
            note = "Short delivery." if r["missing_codes"] else None
            return envelope(r, 1.0, [f"delivery:{r['delivery_id']}"],
                            bool(r["missing_codes"]), note)
        if name == "report_damage":
            r = tools.report_damage(s, str(args["carton_code"]), str(args.get("note", "")),
                                    confirm=False)
            if not r.get("needs_confirmation"):
                return envelope(r, 0.0, [], True, "Unknown carton code.")
            code = tools.normalize_code(str(args["carton_code"]))
            return envelope(r, 1.0, [f"carton:{code}"], True,
                            "A person must confirm this in the app.")
        if name == "list_open_alerts":
            r = tools.list_open_alerts(s)
            return envelope(r, 1.0, [f"alert:{a['id']}" for a in r["alerts"]], False)
        if name == "resolve_alert":
            r = tools.resolve_alert(s, int(args["alert_id"]), str(args["note"]))
            if not r["resolved"]:
                return envelope(r, 0.0, [], True, r.get("error", "No open alert with that id."))
            return envelope(r, 1.0, [f"alert:{r['alert_id']}"], False)
        if name == "list_cartons":
            rows = [tools.summarize(c) for c in s.list_cartons()]
            return envelope({"count": len(rows), "cartons": rows}, 1.0,
                            [f"carton:{r['label_code']}" for r in rows], False)
        raise KeyError(name)

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one JSON-RPC request; returns the result object or None for notifications."""
        method = msg.get("method")
        if method == "initialize":
            return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            params = msg.get("params") or {}
            try:
                out = self.call(str(params.get("name")), params.get("arguments") or {})
            except KeyError:
                return {"isError": True, "content": [
                    {"type": "text", "text": "unknown tool or missing argument"}]}
            return {"content": [{"type": "text", "text": json.dumps(out)}]}
        if msg.get("id") is None:
            return None
        raise ValueError(f"unsupported method {method}")


def serve(server: AmberMcpServer, lines: Any = None, out: Any = None) -> None:
    lines = sys.stdin if lines is None else lines
    out = sys.stdout if out is None else out
    for line in lines:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32700, "message": "parse error"}}) + "\n")
            out.flush()
            continue
        try:
            result = server.handle(msg)
            reply: dict[str, Any] | None = (
                {"jsonrpc": "2.0", "id": msg["id"], "result": result}
                if result is not None and msg.get("id") is not None else None)
        except Exception as exc:  # noqa: BLE001 - JSON-RPC error boundary (dev stdio loop)
            reply = ({"jsonrpc": "2.0", "id": msg.get("id"),
                      "error": {"code": -32601, "message": str(exc)}}
                     if msg.get("id") is not None else None)
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()


def build_store() -> AmberStore:
    """The app's SQLite-backed store (dev stdio use)."""
    from app.amber.sql_store import SqlAmberStore
    from app.db import get_engine, init_db

    engine = get_engine()
    init_db(engine)
    return SqlAmberStore(engine)


def main() -> None:
    serve(AmberMcpServer(build_store()))


if __name__ == "__main__":
    main()
