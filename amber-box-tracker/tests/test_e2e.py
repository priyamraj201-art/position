"""End-to-end API flow through the real app: Amber chat, alerts, light queue, MCP.

Covers the API and Amber parts only. Camera/vision and device (ESP32) behaviour
are not exercised here.
"""
from __future__ import annotations

import pytest
from app import devices
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.db as db_module

    db_module._engine = None
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "e2e.db")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    devices.reset()
    with TestClient(create_app()) as test_client:
        yield test_client
    devices.reset()


def _chat(client, message, **extra):
    response = client.post("/api/amber/chat", json={"message": message, **extra})
    assert response.status_code == 200
    return response.json()


def _rpc(client, method, params, msg_id=1):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    return client.post("/mcp", json=body).json()


def test_where_does_it_go_from_the_database(client):
    reply = _chat(client, "where does KYC1:BV2401 go?")
    assert "L2-B2" in reply["reply"]
    assert reply["needs_confirmation"] is False


def test_delivery_status_matches_the_deliveries_api(client):
    reply = _chat(client, "status of DEL-2211")
    assert "0 of 6" in reply["reply"]
    client.post("/api/deliveries/DEL-2211/receive")
    assert "6 of 6" in _chat(client, "status of DEL-2211")["reply"]


def test_damage_needs_confirm_then_raises_one_alert(client):
    first = _chat(client, "BV2401 is damaged: dent")
    assert first["needs_confirmation"] is True
    assert client.get("/api/alerts").json()["alerts"] == []
    done = _chat(client, "BV2401 is damaged: dent", confirm=True)
    assert done["needs_confirmation"] is False
    alerts = client.get("/api/alerts").json()["alerts"]
    assert len(alerts) == 1
    again = _chat(client, "BV2401 is damaged: dent", confirm=True)
    assert again["needs_confirmation"] is False
    assert len(client.get("/api/alerts").json()["alerts"]) == 1


def test_light_via_mcp_queues_a_blink(client):
    result = _rpc(
        client,
        "tools/call",
        {"name": "find_carton", "arguments": {"query": "BV2401", "auto_locate": True}},
    )["result"]
    assert result is not None
    assert devices.pending_commands("shelf-light-01")[0]["cmd"] == "blink"


def test_unknown_carton_is_not_guessed(client):
    reply = _chat(client, "where does ZZ9999 go?")
    assert "L2-" not in reply["reply"]
