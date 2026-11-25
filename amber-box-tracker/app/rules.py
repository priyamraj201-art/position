"""Sighting evaluation rules + not_arrived timer (PRD-02 section 2.1).

Every decoded sighting flows through record_sighting, which stores it,
updates the carton's last-seen state, and applies three rules:
  wrong_floor, wrong_shelf (with shelf-light commands), confirmed put-away.
check_not_arrived runs every 30 s from the app background task; its clock
is injectable for tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app import alerts, devices
from app.models import Alert, Camera, Carton, Shelf, Sighting, utcnow

WRONG_FLOOR_KINDS = {"hoist", "floor_entrance", "aisle"}


def record_sighting(
    session: Session,
    carton: Carton,
    camera: Camera,
    source: str = "cctv",
    level: int | None = None,
    shelf_id: int | None = None,
    seen_at: datetime | None = None,
    snapshot_path: str | None = None,
    bbox: dict[str, Any] | None = None,
    track_id: int | None = None,
    is_resting: bool = False,
) -> Sighting:
    """Store a sighting and apply the PRD-02 section 2.1 rules."""
    if level is None:
        level = camera.level
    sighting = Sighting(
        carton_id=carton.id,
        camera_id=camera.id,
        source=source,
        level=level,
        shelf_id=shelf_id,
        seen_at=seen_at or utcnow(),
        snapshot_path=snapshot_path,
        bbox=bbox,
        track_id=track_id,
    )
    session.add(sighting)

    carton.last_seen_at = sighting.seen_at
    carton.last_seen_level = level
    carton.last_seen_shelf_id = shelf_id
    carton.last_seen_camera_id = camera.id
    if snapshot_path:
        carton.last_snapshot = snapshot_path
    session.add(carton)

    dest_shelf = session.get(Shelf, carton.dest_shelf_id)
    dest_shelf_code = dest_shelf.code if dest_shelf else "?"

    # Rule 1: wrong floor (gate and pov cameras never trigger this).
    if (
        camera.kind in WRONG_FLOOR_KINDS
        and camera.level is not None
        and camera.level != carton.dest_level
    ):
        message = (
            f"Box {carton.label_code} ({carton.item_name}, {carton.po_number}) "
            f"is on Floor {camera.level} - it belongs on Floor "
            f"{carton.dest_level}, shelf {dest_shelf_code}."
        )
        alerts.create_alert(
            session,
            "wrong_floor",
            message,
            carton_id=carton.id,
            camera_id=camera.id,
            snapshot_path=snapshot_path,
        )
        carton.status = "misplaced"
        session.add(carton)

    # Rule 2: wrong shelf (resting on an aisle camera, wrong marker).
    if (
        camera.kind == "aisle"
        and is_resting
        and shelf_id is not None
        and shelf_id != carton.dest_shelf_id
    ):
        current_shelf = session.get(Shelf, shelf_id)
        current_code = current_shelf.code if current_shelf else "?"
        message = (
            f"Box {carton.label_code} is on {current_code} - "
            f"it should be on {dest_shelf_code}."
        )
        light_events = [
            c
            for c in (
                devices.queue_command(
                    current_shelf.light_device_id if current_shelf else None,
                    "blink_red",
                    20,
                ),
                devices.queue_command(
                    dest_shelf.light_device_id if dest_shelf else None, "blink", 20
                ),
            )
            if c
        ]
        alerts.create_alert(
            session,
            "wrong_shelf",
            message,
            carton_id=carton.id,
            camera_id=camera.id,
            snapshot_path=snapshot_path,
            shelf_light_events=light_events,
        )
        carton.status = "misplaced"
        session.add(carton)

    # Rule 3: confirmed put-away (resting on the destination shelf).
    if (
        camera.kind == "aisle"
        and is_resting
        and shelf_id is not None
        and shelf_id == carton.dest_shelf_id
    ):
        carton.status = "stored"
        session.add(carton)
        alerts.auto_resolve_for_carton(session, carton.id)
        devices.queue_command(
            dest_shelf.light_device_id if dest_shelf else None, "ack", 2
        )

    session.commit()
    session.refresh(sighting)
    return sighting


def check_not_arrived(
    session: Session,
    now: datetime | None = None,
    minutes: int = 2,
) -> list[Alert]:
    """Alert on received cartons not seen on their destination level in time.

    Clock and window are injectable for tests (fake clock per PRD-02 2.1).
    """
    now = now or utcnow()
    created: list[Alert] = []
    cartons = session.exec(
        select(Carton).where(Carton.status == "received")
    ).all()
    for carton in cartons:
        if carton.received_at is None:
            continue
        if now - carton.received_at < timedelta(minutes=minutes):
            continue
        seen_dest = session.exec(
            select(Sighting).where(
                Sighting.carton_id == carton.id,
                Sighting.level == carton.dest_level,
                Sighting.seen_at >= carton.received_at,
            )
        ).first()
        if seen_dest is not None:
            continue
        message = (
            f"Box {carton.label_code} ({carton.item_name}) was received at "
            f"the gate but has not been seen on Floor {carton.dest_level} "
            f"within {minutes} min."
        )
        alert, was_created = alerts.create_alert(
            session,
            "not_arrived",
            message,
            carton_id=carton.id,
            delivery_id=carton.delivery_id,
        )
        if was_created:
            created.append(alert)
    return created
