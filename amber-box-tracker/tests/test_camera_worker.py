"""Camera worker persistence boundary (Track 1/Track 2 seam).

SightingEvent.carton_code arrives QR-prefixed (KYC1:BV2401); stored labels are
bare (BV2401). The worker must key pipeline destinations with the prefix and
strip it again when persisting sightings, or every camera sighting is dropped.
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

pytest.importorskip("cv2")  # app.vision imports cv2 at module load

from app.db import get_engine, init_db
from app.models import Alert, Sighting
from app.seed import seed_if_empty
from app.vision.pipeline import SightingEvent
from app.vision.worker import CameraWorker


@pytest.fixture
def engine():
    eng = get_engine(":memory:")
    init_db(eng)
    with Session(eng) as session:
        seed_if_empty(session)
    return eng


def _worker(engine, camera_id):
    worker = object.__new__(CameraWorker)  # skip source setup; persistence seam only
    worker.camera_id = camera_id
    worker.engine = engine
    return worker


def test_pipeline_destinations_are_prefixed(engine):
    _, _, carton_dests, _ = _worker(engine, "CAM-AISLE-2")._load_context()
    assert "KYC1:BV2401" in carton_dests
    assert "BV2401" not in carton_dests


def test_prefixed_sighting_is_persisted_and_alerted(engine):
    worker = _worker(engine, "CAM-AISLE-2")
    _, _, _, shelf_code_to_id = worker._load_context()
    event = SightingEvent(
        carton_code="KYC1:BV2401",  # QR payload form, not the stored form
        camera_id="CAM-AISLE-2",
        level=2,
        shelf_code="L2-B1",  # dest is L2-B2: resting here must raise wrong_shelf
        is_resting=True,
        seen_at=0.0,
        bbox=(0, 0, 10, 10),
        track_id=1,
    )
    worker._persist_sightings([event], shelf_code_to_id)
    with Session(engine) as session:
        sightings = session.exec(select(Sighting)).all()
        assert len(sightings) == 1
        alerts = session.exec(select(Alert)).all()
        assert [a.type for a in alerts] == ["wrong_shelf"]
