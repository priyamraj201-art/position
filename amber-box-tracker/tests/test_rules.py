"""Rules engine tests (PRD-02 section 2.1), incl. fake-clock not_arrived."""
from __future__ import annotations

from datetime import timedelta

import pytest
from app import devices, rules
from app.db import get_engine, init_db
from app.models import Alert, Camera, Carton, Shelf, utcnow
from app.seed import seed_if_empty
from sqlmodel import Session, select


@pytest.fixture(autouse=True)
def _reset_devices():
    devices.reset()
    yield
    devices.reset()


@pytest.fixture
def session():
    engine = get_engine(":memory:")
    init_db(engine)
    with Session(engine) as s:
        seed_if_empty(s)
        yield s


def get_carton(session, code="BV2401"):
    return session.exec(select(Carton).where(Carton.label_code == code)).one()


def open_alerts(session, alert_type=None):
    query = select(Alert).where(Alert.status == "open")
    if alert_type:
        query = query.where(Alert.type == alert_type)
    return list(session.exec(query).all())


def test_wrong_floor_on_hoist_camera(session):
    carton = get_carton(session)  # dest level 2
    hoist = session.get(Camera, "CAM-HOIST-3")  # level 3
    rules.record_sighting(session, carton, hoist)
    found = open_alerts(session, "wrong_floor")
    assert len(found) == 1
    assert "Floor 3" in found[0].message and "Floor 2" in found[0].message
    assert "BV2401" in found[0].message
    assert carton.status == "misplaced"


def test_wrong_floor_dedup_keeps_one_open_alert(session):
    carton = get_carton(session)
    hoist = session.get(Camera, "CAM-HOIST-3")
    rules.record_sighting(session, carton, hoist)
    rules.record_sighting(session, carton, hoist)
    assert len(open_alerts(session, "wrong_floor")) == 1
    assert session.exec(select(Alert).where(Alert.type == "wrong_floor")).all().__len__() == 1


def test_gate_camera_never_triggers_wrong_floor(session):
    carton = get_carton(session)
    gate = session.get(Camera, "CAM-GATE")  # level 0, kind gate
    rules.record_sighting(session, carton, gate)
    assert open_alerts(session) == []
    assert carton.status == "received"


def test_wrong_shelf_queues_light_commands(session):
    carton = get_carton(session, "BV2401")  # dest L2-B2 (shelf-light-01)
    aisle = session.get(Camera, "CAM-AISLE-2")
    wrong_shelf = session.exec(select(Shelf).where(Shelf.code == "L2-B3")).one()
    rules.record_sighting(
        session, carton, aisle, shelf_id=wrong_shelf.id, is_resting=True
    )
    found = open_alerts(session, "wrong_shelf")
    assert len(found) == 1
    assert "L2-B3" in found[0].message and "L2-B2" in found[0].message
    red = devices.pending_commands("shelf-light-02")
    blue = devices.pending_commands("shelf-light-01")
    assert red == [{"cmd": "blink_red", "color": "red", "seconds": 20}]
    assert blue == [{"cmd": "blink", "color": "blue", "seconds": 20}]


def test_put_away_stores_and_auto_resolves(session):
    carton = get_carton(session, "BV2401")
    aisle = session.get(Camera, "CAM-AISLE-2")
    wrong_shelf = session.exec(select(Shelf).where(Shelf.code == "L2-B3")).one()
    rules.record_sighting(
        session, carton, aisle, shelf_id=wrong_shelf.id, is_resting=True
    )
    assert len(open_alerts(session, "wrong_shelf")) == 1
    rules.record_sighting(
        session, carton, aisle, shelf_id=carton.dest_shelf_id, is_resting=True
    )
    assert carton.status == "stored"
    assert open_alerts(session) == []
    resolved = session.exec(
        select(Alert).where(Alert.type == "wrong_shelf")
    ).one()
    assert resolved.status == "resolved"
    assert resolved.resolved_note == "auto-resolved"
    assert devices.pending_commands("shelf-light-01")[-1] == {
        "cmd": "ack", "color": "green", "seconds": 2,
    }


def test_not_arrived_with_fake_clock(session):
    carton = get_carton(session)
    carton.received_at = utcnow() - timedelta(minutes=10)
    session.add(carton)
    session.commit()
    now = utcnow()
    created = rules.check_not_arrived(session, now=now, minutes=2)
    assert len(created) == 1
    assert created[0].type == "not_arrived"
    assert "BV2401" in created[0].message
    # Second pass dedups.
    assert rules.check_not_arrived(session, now=now, minutes=2) == []


def test_not_arrived_skips_within_window_and_unreceived(session):
    carton = get_carton(session)
    carton.received_at = utcnow() - timedelta(seconds=30)
    session.add(carton)
    session.commit()
    assert rules.check_not_arrived(session, now=utcnow(), minutes=2) == []
    # received_at None (delivery not yet received) is skipped.
    carton.received_at = None
    session.add(carton)
    session.commit()
    later = utcnow() + timedelta(hours=1)
    assert rules.check_not_arrived(session, now=later, minutes=2) == []


def test_not_arrived_cleared_by_dest_level_sighting(session):
    carton = get_carton(session)
    carton.received_at = utcnow() - timedelta(minutes=10)
    session.add(carton)
    session.commit()
    aisle = session.get(Camera, "CAM-AISLE-2")  # level 2 == dest_level
    rules.record_sighting(session, carton, aisle)
    assert rules.check_not_arrived(session, now=utcnow(), minutes=2) == []
