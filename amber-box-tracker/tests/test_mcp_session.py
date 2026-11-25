"""Submission-gate test: a REAL JSON-RPC session against the mounted /mcp.

Tier 1 (here): an actual HTTP JSON-RPC client session - initialize,
tools/list, tools/call - against Track 4's adapter mounted in-process.
Tier 2 (before demo claims): the official MCP SDK client against the same
endpoint; run once Track 4's SDK swap lands, result recorded separately.

Skips cleanly until app/amber/mcp_server.py exists on main.
"""
from __future__ import annotations

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    import app.db as db_module

    db_module._engine = None
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_mcp_jsonrpc_session(client):
    pytest.importorskip(
        "app.amber.mcp_http",
        reason="Track 4 MCP adapter not on this branch yet - tier-1 gate test activates when it lands",
    )
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = client.post("/mcp", json=rpc)
    assert response.status_code == 200
    assert response.json().get("result") is not None

    rpc = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    tools = client.post("/mcp", json=rpc).json()["result"]
    names = {t["name"] for t in tools["tools"]}
    assert "find_carton" in names

    rpc = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "find_carton", "arguments": {"query": "BV2401"}},
    }
    result = client.post("/mcp", json=rpc).json()["result"]
    assert result is not None


def test_mcp_transport_behaviour(client):
    pytest.importorskip(
        "app.amber.mcp_http",
        reason="Track 4 MCP adapter not on this branch yet",
    )
    # Batch request
    batch = [
        {"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}},
    ]
    response = client.post("/mcp", json=batch)
    assert response.status_code == 200
    assert len(response.json()) == 2
    # Notification (no id) -> 202
    note = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    assert client.post("/mcp", json=note).status_code == 202
    # Invalid JSON -> 400 parse error
    bad = client.post(
        "/mcp", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert bad.status_code == 400
    # GET -> 405 (no SSE, no session ids)
    assert client.get("/mcp").status_code == 405
