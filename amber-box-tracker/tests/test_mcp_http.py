"""MCP mounted in a FastAPI app over the real SQLModel store: shared in-process light queue."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from app import devices
from app.amber.mcp_http import build_router
from app.amber.sql_store import SqlAmberStore
from app.db import get_engine, init_db
from app.seed import seed_if_empty
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = get_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as s:
        seed_if_empty(s)
    devices.reset()
    app = FastAPI()
    app.include_router(build_router(lambda: SqlAmberStore(engine)))
    with TestClient(app) as c:
        yield c
    engine.dispose()


def _rpc(client: TestClient, method: str, params: dict[str, Any] | None = None,
         id_: int = 1) -> Any:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body)


def test_initialize_and_list(client: TestClient) -> None:
    init = _rpc(client, "initialize").json()["result"]
    assert init["serverInfo"]["name"] == "amber-box-tracker"
    names = {t["name"] for t in _rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"find_carton", "where_does_this_go", "delivery_status", "report_damage",
            "list_open_alerts"} <= names


def test_notification_gets_202_and_get_is_405(client: TestClient) -> None:
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert client.get("/mcp").status_code == 405


def test_bad_json_and_bad_message(client: TestClient) -> None:
    assert client.post("/mcp", content=b"{nope").status_code == 400
    assert client.post("/mcp", json={"id": 1}).json()["error"]["code"] == -32600


def test_batch(client: TestClient) -> None:
    batch = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "initialize"}]
    replies = client.post("/mcp", json=batch).json()
    assert [r["id"] for r in replies] == [1, 2]


def test_tool_call_returns_envelope(client: TestClient) -> None:
    r = _rpc(client, "tools/call", {"name": "where_does_this_go",
                                    "arguments": {"carton_code": "KYC1:CH0201"}})
    env = json.loads(r.json()["result"]["content"][0]["text"])
    assert env["answer"]["destination"] == "Floor 3, shelf L3-A1"
    assert env["confidence"] == 1.0 and env["sources"] == ["carton:KYC1:CH0201"]


def test_locate_reaches_the_app_light_queue(client: TestClient) -> None:
    _rpc(client, "tools/call", {"name": "find_carton", "arguments": {
        "query": "KYC1:DM0402", "auto_locate": True}})
    assert devices.pending_commands("shelf-light-02") == [
        {"cmd": "blink", "color": "blue", "seconds": 30}]
