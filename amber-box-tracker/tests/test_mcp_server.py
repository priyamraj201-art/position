"""MCP adapter: envelope fields, confidence bands, JSON-RPC handling. Uses the fake store."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.amber.envelope import find_confidence
from app.amber.mcp_server import TOOLS, AmberMcpServer, serve
from test_amber import FakeStore


@pytest.fixture()
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture()
def server(store: FakeStore) -> AmberMcpServer:
    return AmberMcpServer(store)


def _match(score: float, item: str = "x") -> dict[str, Any]:
    return {"score": score, "item_name": item, "label_code": "KYC1:AAAAAA"}


def test_every_envelope_has_required_fields(server: AmberMcpServer) -> None:
    calls = [("find_carton", {"query": "strainer"}),
             ("where_does_this_go", {"carton_code": "BV2401"}),
             ("delivery_status", {"delivery_id": "DEL-2211"}),
             ("report_damage", {"carton_code": "BV2401"}),
             ("list_open_alerts", {}), ("list_cartons", {})]
    for name, args in calls:
        out = server.call(name, args)
        assert set(out) == {"answer", "confidence", "sources", "needs_human_review", "note"}
        assert 0.0 <= out["confidence"] <= 1.0
        assert out["sources"], name


def test_no_match_is_low_confidence_and_flagged(server: AmberMcpServer) -> None:
    out = server.call("find_carton", {"query": "unobtainium"})
    assert (out["confidence"], out["needs_human_review"], out["sources"]) == (0.0, True, [])


def test_exact_code_is_high_confidence(server: AmberMcpServer) -> None:
    out = server.call("find_carton", {"query": "KYC1:YS0601"})
    assert out["confidence"] == 1.0 and out["needs_human_review"] is False
    assert out["sources"] == ["carton:KYC1:YS0601"]


def test_confidence_bands() -> None:
    assert find_confidence({"matches": [_match(0.92)]}) == (0.92, False, None)
    assert find_confidence({"matches": [_match(0.8)]})[1] is False
    conf, review, _ = find_confidence({"matches": [_match(0.65)]})
    assert conf == 0.65 and review is True


def test_ambiguous_different_items_flagged() -> None:
    result = {"matches": [_match(0.95, "ball valve"), _match(0.93, "butterfly valve")]}
    assert find_confidence(result)[1] is True
    same = {"matches": [_match(0.95, "ball valve"), _match(0.95, "ball valve")]}
    assert find_confidence(same)[1] is False


def test_unknown_carton_flagged(server: AmberMcpServer) -> None:
    out = server.call("where_does_this_go", {"carton_code": "NOPE00"})
    assert out["needs_human_review"] is True and out["confidence"] == 0.0


def test_short_delivery_flagged_and_seen_not_caller_supplied(server: AmberMcpServer) -> None:
    out = server.call("delivery_status", {"delivery_id": "DEL-2211", "seen": ["KYC1:YS0601"]})
    assert out["needs_human_review"] is True
    assert out["answer"]["seen"] == 2  # from the store, the extra argument is ignored
    schema = next(t for t in TOOLS if t["name"] == "delivery_status")["inputSchema"]
    assert list(schema["properties"]) == ["delivery_id"]


def test_damage_never_records_over_mcp(server: AmberMcpServer, store: FakeStore) -> None:
    out = server.call("report_damage", {"carton_code": "BV2401", "note": "x", "confirm": True})
    assert out["answer"]["needs_confirmation"] is True and out["needs_human_review"] is True
    assert store.damaged == []
    assert "confirm" not in next(t for t in TOOLS if t["name"] == "report_damage")[
        "inputSchema"]["properties"]


def test_auto_locate_passes_through(server: AmberMcpServer, store: FakeStore) -> None:
    server.call("find_carton", {"query": "strainer", "auto_locate": True})
    assert store.located == ["KYC1:YS0601"]


def test_unknown_tool_raises(server: AmberMcpServer) -> None:
    with pytest.raises(KeyError):
        server.call("drop_tables", {})


def test_stdio_roundtrip(server: AmberMcpServer) -> None:
    req = [{"jsonrpc": "2.0", "id": 1, "method": "initialize"},
           {"jsonrpc": "2.0", "method": "notifications/initialized"},
           {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
           {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_open_alerts", "arguments": {}}},
           {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}}]
    lines = [json.dumps(r) for r in req] + ["not json"]
    out = io.StringIO()
    serve(server, lines, out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4, None]
    assert len(replies[1]["result"]["tools"]) == 7
    body = json.loads(replies[2]["result"]["content"][0]["text"])
    assert body["answer"]["count"] == 1
    assert replies[3]["result"]["isError"] is True
    assert replies[4]["error"]["code"] == -32700


def test_resolve_requires_human_note(server: AmberMcpServer, store: FakeStore) -> None:
    empty = server.call("resolve_alert", {"alert_id": 1, "note": "   "})
    assert empty["needs_human_review"] is True and store.resolved == []
    ok = server.call("resolve_alert", {"alert_id": 1, "note": " moved to L2-B2 "})
    assert ok["answer"]["resolved"] is True and ok["needs_human_review"] is False
    assert store.resolved == [(1, "moved to L2-B2")]
    assert server.call("resolve_alert", {"alert_id": 9, "note": "x"})["needs_human_review"]


def test_unknown_or_malformed_codes_are_rejected_not_stored(
        server: AmberMcpServer, store: FakeStore) -> None:
    for code in ("KYC1:ZZZZZZ", "garbage", "KYC1:", ""):
        w = server.call("where_does_this_go", {"carton_code": code})
        assert w["needs_human_review"] is True and w["answer"]["found"] is False
        d = server.call("report_damage", {"carton_code": code})
        assert d["needs_human_review"] is True
    assert store.damaged == [] and store.resolved == []
