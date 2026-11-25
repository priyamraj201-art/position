"""Seed and model tests: PR 1a must leave a coherent, seeded database."""
from __future__ import annotations

from app import models
from app.db import get_engine, init_db
from app.seed import seed_if_empty
from sqlmodel import Session, select


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def test_seed_loads_all_entities():
    with make_session() as session:
        assert seed_if_empty(session) is True
        assert len(session.exec(select(models.Shelf)).all()) == 5
        assert len(session.exec(select(models.Carton)).all()) == 8
        assert len(session.exec(select(models.Delivery)).all()) == 2
        assert len(session.exec(select(models.Camera)).all()) == 4
        assert len(session.exec(select(models.PurchaseOrder)).all()) == 2
        assert len(session.exec(select(models.ShelfLight)).all()) == 2


def test_seed_is_idempotent():
    with make_session() as session:
        assert seed_if_empty(session) is True
        assert seed_if_empty(session) is False
        assert len(session.exec(select(models.Carton)).all()) == 8


def test_label_codes_unique_and_shaped():
    with make_session() as session:
        seed_if_empty(session)
        cartons = session.exec(select(models.Carton)).all()
        codes = [c.label_code for c in cartons]
        assert len(codes) == len(set(codes))
        for code in codes:
            assert len(code) == 6 and code.isalnum() and code.upper() == code


def test_carton_destinations_match_shelf_levels():
    with make_session() as session:
        seed_if_empty(session)
        for carton in session.exec(select(models.Carton)).all():
            shelf = session.get(models.Shelf, carton.dest_shelf_id)
            assert shelf is not None
            assert carton.dest_level == shelf.level
            assert carton.dest_facility_id == shelf.facility_id


def test_delivery_2211_contents():
    with make_session() as session:
        seed_if_empty(session)
        cartons = session.exec(
            select(models.Carton).where(models.Carton.delivery_id == "DEL-2211")
        ).all()
        assert len(cartons) == 6
        by_code = {c.label_code: c for c in cartons}
        dm0402 = by_code["DM0402"]
        shelf = session.get(models.Shelf, dm0402.dest_shelf_id)
        assert shelf.code == "L2-B3"
        assert dm0402.item_name == "AHU-3 damper kit"


def test_gate_camera_is_level_zero_and_not_a_destination():
    with make_session() as session:
        seed_if_empty(session)
        gate = session.get(models.Camera, "CAM-GATE")
        assert gate.kind == "gate" and gate.level == 0
        # No carton has level 0 as a destination: gate never counts as arrival.
        for carton in session.exec(select(models.Carton)).all():
            assert carton.dest_level != 0
