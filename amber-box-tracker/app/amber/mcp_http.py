"""MCP over HTTP, mounted inside the FastAPI app (submission transport).

Add to `app/main.py` (Track 1):

    from app.amber.mcp_http import build_router
    from app.amber.sql_store import SqlAmberStore
    app.include_router(build_router(lambda: SqlAmberStore(get_engine())))

Endpoint: `POST /mcp` takes one JSON-RPC message or a batch and replies with JSON (the "streamable
HTTP" transport without server push). Notifications get `202`. `GET /mcp` is `405`.

The handler is `async def` on purpose: `app.devices.queue_command` sets an `asyncio.Event`, which
must happen on the event loop thread. Running it in the loop (not a worker thread) also keeps the
light queue and the SSE broadcaster shared with the rest of the app.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.amber.mcp_server import AmberMcpServer
from app.amber.sql_store import SqlAmberStore
from app.amber.tools import AmberStore

__all__ = ["SqlAmberStore", "build_router"]  # main.py imports SqlAmberStore from here

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_ERROR = -32601


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _one(server: AmberMcpServer, msg: Any) -> dict[str, Any] | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "invalid request")
    msg_id = msg.get("id")
    try:
        result = server.handle(msg)
    except Exception as exc:  # noqa: BLE001 - JSON-RPC error boundary: any handler failure becomes an error reply
        return _error(msg_id, METHOD_ERROR, str(exc)) if msg_id is not None else None
    if result is None or msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def build_router(store_factory: Callable[[], AmberStore], path: str = "/mcp") -> APIRouter:
    router = APIRouter()

    @router.post(path)
    async def mcp_post(request: Request) -> Response:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "parse error"), status_code=400)
        server = AmberMcpServer(store_factory())
        if isinstance(body, list):
            replies = [r for r in (_one(server, m) for m in body) if r is not None]
            return JSONResponse(replies) if replies else Response(status_code=202)
        reply = _one(server, body)
        return JSONResponse(reply) if reply is not None else Response(status_code=202)

    @router.get(path)
    async def mcp_get() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    return router
