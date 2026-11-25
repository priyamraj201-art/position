"""Fuzzy find over the real API and Amber's find_carton (seeded database)."""
from __future__ import annotations

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.db as db_module

    db_module._engine = None
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "find.db")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def _codes(body):
    return [m["label_code"] for m in body["answer"]["matches"]]


def test_exact_code_ranks_first_with_full_confidence(client):
    body = client.get("/api/find", params={"q": "BV2401"}).json()
    assert _codes(body)[0] == "BV2401"
    assert body["confidence"] == 1.0
    assert body["needs_human_review"] is False


def test_qr_prefix_is_stripped(client):
    plain = client.get("/api/find", params={"q": "BV2401"}).json()
    prefixed = client.get("/api/find", params={"q": "KYC1:BV2401"}).json()
    assert _codes(prefixed) == _codes(plain)


def test_case_insensitive_substring_on_item_name(client):
    body = client.get("/api/find", params={"q": "BALL VALVE"}).json()
    assert "BV2401" in _codes(body)


def test_typo_still_finds_the_valve(client):
    body = client.get("/api/find", params={"q": "ball valv"}).json()
    assert "BV2401" in _codes(body)


def test_nonsense_query_asks_for_human_review(client):
    body = client.get("/api/find", params={"q": "zzzzzz9"}).json()
    assert body["answer"]["matches"] == []
    assert body["needs_human_review"] is True
    assert body["confidence"] == 0.0


def test_matches_carry_destination(client):
    top = client.get("/api/find", params={"q": "BV2401"}).json()["answer"]["matches"][0]
    assert top["dest_shelf"] == "L2-B2"


def test_amber_find_agrees_with_api_top_hit(client):
    api_top = _codes(client.get("/api/find", params={"q": "BV2401"}).json())[0]
    reply = client.post("/api/amber/chat", json={"message": "find BV2401"}).json()
    call = reply["tool_calls"][0]
    assert call["name"] == "find_carton"
    assert call["result"]["matches"][0]["label_code"] == f"KYC1:{api_top}"
    assert "L2-B2" in reply["reply"]
