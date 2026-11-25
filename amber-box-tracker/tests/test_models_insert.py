"""Insert tests for timestamped models (Track 4 review on PR #6).

sqlmodel 0.0.49 enforces timezone-aware datetimes on its default DateTime
mapping; our models annotate naive UTC via pydantic.NaiveDatetime. These
tests pin that inserts and reads work for Sighting, Alert, DeliveryIssue.
"""
from __future__ import annotations

from datetime import datetime

from app import models
from app.db import get_engine, init_db
from app.models import utcnow
from app.seed import seed_if_empty
from sqlmodel import Session, select


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    session = Session(engine)
    seed_if_empty(session)
    return session


def test_sighting_insert_with_default_timestamp():
    with make_session() as session:
        carton = session.exec(select(models.Carton)).first()
        camera = session.get(models.Camera, "CAM-AISLE-2")
        sighting = models.Sighting(
            carton_id=carton.id, camera_id=camera.id, level=camera.level
        )
        session.add(sighting)
        session.commit()
        session.refresh(sighting)
        assert sighting.id is not None
        assert isinstance(sighting.seen_at, datetime)
        assert sighting.seen_at.tzinfo is None  # naive UTC by convention


def test_alert_insert_with_default_timestamp():
    with make_session() as session:
        carton = session.exec(select(models.Carton)).first()
        alert = models.Alert(
            type="wrong_floor", message="test", carton_id=carton.id
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        assert alert.id is not None
        assert alert.status == "open"
        assert isinstance(alert.created_at, datetime)


def test_delivery_issue_insert_with_default_timestamp():
    with make_session() as session:
        issue = models.DeliveryIssue(
            delivery_id="DEL-2211",
            missing_items=[{"label_code": "DM0402"}],
        )
        session.add(issue)
        session.commit()
        session.refresh(issue)
        assert issue.id is not None
        assert issue.missing_items[0]["label_code"] == "DM0402"
        assert isinstance(issue.created_at, datetime)


def test_carton_received_at_naive_write():
    with make_session() as session:
        carton = session.exec(select(models.Carton)).first()
        carton.received_at = utcnow()
        session.add(carton)
        session.commit()
        session.refresh(carton)
        assert carton.received_at is not None
        assert carton.received_at.tzinfo is None
