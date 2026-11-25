"""Alert service tests: dedup keys, delivery issues, idempotent resolve."""
from __future__ import annotations

import pytest
from app import alerts
from app.db import get_engine, init_db
from app.models import Carton, DeliveryIssue
from app.seed import seed_if_empty
from sqlmodel import Session, select


@pytest.fixture
def session():
    engine = get_engine(":memory:")
    init_db(engine)
    with Session(engine) as s:
        seed_if_empty(s)
        yield s


def get_carton(session, code="DM0402"):
    return session.exec(select(Carton).where(Carton.label_code == code)).one()


def test_resolve_is_idempotent(session):
    alert, _ = alerts.create_alert(session, "damaged", "first", carton_id=1)
    alerts.resolve_alert(session, alert.id, "fixed it")
    again = alerts.resolve_alert(session, alert.id, "different note")
    assert again is not None
    assert again.status == "resolved"
    assert again.resolved_note == "fixed it"  # not overwritten


def test_delivery_scoped_dedup(session):
    first, created1 = alerts.create_alert(
        session, "short_delivery", "missing DM0402", delivery_id="DEL-2211"
    )
    second, created2 = alerts.create_alert(
        session, "short_delivery", "missing DM0402 again", delivery_id="DEL-2211"
    )
    assert created1 is True and created2 is False
    assert first.id == second.id


def test_report_damage_creates_issue_and_alert(session):
    carton = get_carton(session)
    issue, alert = alerts.report_damage(session, carton, "crushed corner")
    assert issue.delivery_id == carton.delivery_id
    assert issue.damaged_items[0]["label_code"] == "DM0402"
    assert issue.damaged_items[0]["note"] == "crushed corner"
    assert alert.type == "damaged"
    assert alert.carton_id == carton.id
    assert alert.delivery_id == carton.delivery_id
    # Alert dedups per carton; each report still records its own issue row.
    _, alert2 = alerts.report_damage(session, carton, "water damage")
    assert alert2.id == alert.id
    issues = session.exec(
        select(DeliveryIssue).where(DeliveryIssue.delivery_id == carton.delivery_id)
    ).all()
    assert len(issues) == 2


def test_report_short_delivery_dedups_alert_keeps_issues(session):
    missing = [{"label_code": "DM0402"}]
    issue1, alert1 = alerts.report_short_delivery(session, "DEL-2211", missing)
    issue2, alert2 = alerts.report_short_delivery(session, "DEL-2211", missing)
    assert issue1.id != issue2.id
    assert alert1.id == alert2.id
    assert alert1.type == "short_delivery"
    assert alert1.delivery_id == "DEL-2211"
    assert "DM0402" in alert1.message


def test_report_damage_exact_duplicate_is_idempotent(session):
    carton = get_carton(session)
    issue1, alert1 = alerts.report_damage(session, carton, "crushed corner")
    issue2, alert2 = alerts.report_damage(session, carton, "crushed corner")
    assert issue2.id == issue1.id  # retried Confirm reuses the row
    assert alert2.id == alert1.id
    issues = session.exec(
        select(DeliveryIssue).where(DeliveryIssue.delivery_id == carton.delivery_id)
    ).all()
    assert len(issues) == 1
