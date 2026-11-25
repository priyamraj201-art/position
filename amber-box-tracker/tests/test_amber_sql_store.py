"""Amber tools and MCP adapter over Track 1's real SQLModel tables and seed."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app import devices, models
from app.amber import tools
from app.amber.mcp_server import AmberMcpServer
from app.amber.sql_store import SqlAmberStore
from app.db import get_engine, init_db
from app.seed import seed_if_empty
from sqlmodel import Session, select


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[SqlAmberStore]:
    engine = get_engine(tmp_path / "t.db")
    init_db(engine)
    with Session(engine) as s:
        seed_if_empty(s)
    devices.reset()
    yield SqlAmberStore(engine)
    engine.dispose()


def _sight(store: SqlAmberStore, bare: str) -> None:
    with Session(store._engine) as s:
        c = s.exec(select(models.Carton).where(models.Carton.label_code == bare)).one()
        s.add(models.Sighting(carton_id=c.id, camera_id="CAM-POV", source="phone",
                              seen_at=datetime.now(timezone.utc).replace(tzinfo=None),  # noqa: UP017 - runs on py3.10 too
                              ))
        s.commit()


def test_seed_loads_and_codes_use_qr_form(store: SqlAmberStore) -> None:
    codes = {c.label_code for c in store.list_cartons()}
    assert len(codes) == 8 and "KYC1:BV2401" in codes


def test_where_does_this_go_real_db(store: SqlAmberStore) -> None:
    out = tools.where_does_this_go(store, "bv2401")
    assert out["destination"] == "Floor 2, shelf L2-B2"
    assert tools.where_does_this_go(store, "KYC1:CH0201")["destination"] == "Floor 3, shelf L3-A1"
    assert tools.where_does_this_go(store, "NOPE00")["found"] is False


def test_find_real_db(store: SqlAmberStore) -> None:
    out = tools.find_carton(store, "AHU-3 dampers")
    assert {m["label_code"] for m in out["matches"]} == {"KYC1:DM0401", "KYC1:DM0402"}
    assert tools.find_carton(store, "KYC1:YS0601")["matches"][0]["belongs_at"] == \
        "Floor 2, shelf L2-B1"


def test_delivery_status_from_sightings(store: SqlAmberStore) -> None:
    assert tools.delivery_status(store, "DEL-2211")["seen"] == 0
    for bare in ("BV2401", "BV2402", "BF1201", "YS0601", "DM0401"):
        _sight(store, bare)
    out = tools.delivery_status(store, "DEL-2211")
    assert (out["expected"], out["seen"], out["missing_codes"]) == (6, 5, ["KYC1:DM0402"])


def test_damage_two_step_and_dedup(store: SqlAmberStore) -> None:
    assert tools.report_damage(store, "BV2401", "dent")["needs_confirmation"] is True
    assert tools.list_open_alerts(store)["count"] == 0
    first = tools.report_damage(store, "BV2401", "dent", confirm=True)["alert_id"]
    again = tools.report_damage(store, "BV2401", "dent", confirm=True)["alert_id"]
    assert first == again
    assert tools.list_open_alerts(store)["alerts"][0]["type"] == "damaged"
    with Session(store._engine) as s:
        issue = s.exec(select(models.DeliveryIssue)).one()
        assert issue.damaged_items[0]["label_code"] == "BV2401"


def test_resolve_needs_note_and_closes(store: SqlAmberStore) -> None:
    aid = tools.report_damage(store, "BV2401", "dent", confirm=True)["alert_id"]
    server = AmberMcpServer(store)
    assert server.call("resolve_alert", {"alert_id": aid, "note": " "})["needs_human_review"]
    assert tools.list_open_alerts(store)["count"] == 1
    ok = server.call("resolve_alert", {"alert_id": aid, "note": "replaced"})
    assert ok["answer"]["resolved"] is True and tools.list_open_alerts(store)["count"] == 0


def test_mcp_over_real_db(store: SqlAmberStore) -> None:
    server = AmberMcpServer(store)
    out = server.call("delivery_status", {"delivery_id": "DEL-2211"})
    assert out["needs_human_review"] is True and len(out["answer"]["missing_codes"]) == 6
    assert server.call("where_does_this_go", {"carton_code": "KYC1:ZZZZZZ"})[
        "needs_human_review"] is True
    loc = server.call("find_carton", {"query": "KYC1:DM0402", "auto_locate": True})
    assert loc["answer"]["locate"]["device_id"] == "shelf-light-02"
    assert loc["answer"]["locate"]["queued"] is True
    assert devices.pending_commands("shelf-light-02") == [
        {"cmd": "blink", "color": "blue", "seconds": 30}]


def test_locate_without_light_queues_nothing(store: SqlAmberStore) -> None:
    out = store.locate("KYC1:BF1201")  # shelf L2-B1 has no light
    assert out["queued"] is False and out["shelf"] == "L2-B1"


def test_resolved_alert_is_not_overwritten(store: SqlAmberStore) -> None:
    aid = tools.report_damage(store, "BV2401", "dent", confirm=True)["alert_id"]
    assert store.resolve_alert(aid, "first") is True
    assert store.resolve_alert(aid, "second") is False
    with Session(store._engine) as s:
        assert s.get(models.Alert, aid).resolved_note == "first"


def test_repeated_confirm_is_idempotent_new_note_is_new_report(store: SqlAmberStore) -> None:
    first = tools.report_damage(store, "BV2401", "dent", confirm=True)["alert_id"]
    again = tools.report_damage(store, "BV2401", "dent", confirm=True)["alert_id"]
    other = tools.report_damage(store, "BV2401", "wet box", confirm=True)["alert_id"]
    assert first == again == other  # one open damaged alert per carton
    with Session(store._engine) as s:
        issues = s.exec(select(models.DeliveryIssue)).all()
        assert [i.damaged_items[0]["note"] for i in issues] == ["dent", "wet box"]


def test_get_provider_from_engine_answers_from_the_db(
        store: SqlAmberStore, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.amber.provider import get_provider

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = get_provider(engine=store._engine)
    assert provider.name == "offline"
    assert "Floor 2, shelf L2-B2" in provider.chat("where does BV2401 go?").reply
    assert provider.chat("BV2401 is damaged: dent").needs_confirmation is True
    assert tools.list_open_alerts(store)["count"] == 0
