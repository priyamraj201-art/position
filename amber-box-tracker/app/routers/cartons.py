"""Carton listing, timelines and locate (PRD-02 section 2.2)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app import devices
from app.db import SessionDep
from app.main import envelope
from app.models import Carton, Shelf, Sighting

router = APIRouter(prefix="/api/cartons", tags=["cartons"])


def normalize_code(code: str) -> str:
    """Boundary rule: stored labels are bare 6-char codes; strip KYC1:."""
    return code.upper().removeprefix("KYC1:")


def carton_view(session: Session, carton: Carton) -> dict:
    dest = session.get(Shelf, carton.dest_shelf_id)
    last = session.get(Shelf, carton.last_seen_shelf_id) if carton.last_seen_shelf_id else None
    return {
        "label_code": carton.label_code,
        "item_name": carton.item_name,
        "part_number": carton.part_number,
        "po_number": carton.po_number,
        "delivery_id": carton.delivery_id,
        "status": carton.status,
        "dest_shelf": dest.code if dest else None,
        "dest_level": carton.dest_level,
        "last_seen_level": carton.last_seen_level,
        "last_seen_shelf": last.code if last else None,
        "last_seen_at": carton.last_seen_at.isoformat() if carton.last_seen_at else None,
        "last_snapshot": carton.last_snapshot,
    }


def get_carton_or_404(session: Session, code: str) -> Carton:
    carton = session.exec(
        select(Carton).where(Carton.label_code == normalize_code(code))
    ).first()
    if carton is None:
        raise HTTPException(404, f"unknown carton: {code}")
    return carton


@router.get("")
def list_cartons(session: SessionDep):
    cartons = session.exec(select(Carton)).all()
    return {"cartons": [carton_view(session, c) for c in cartons]}


@router.get("/{code}/timeline")
def timeline(code: str, session: SessionDep):
    carton = get_carton_or_404(session, code)
    sightings = session.exec(
        select(Sighting)
        .where(Sighting.carton_id == carton.id)
        .order_by(Sighting.seen_at)
    ).all()
    return {
        "label_code": carton.label_code,
        "sightings": [
            {
                "seen_at": s.seen_at.isoformat(),
                "camera_id": s.camera_id,
                "source": s.source,
                "level": s.level,
                "shelf_id": s.shelf_id,
                "snapshot_path": s.snapshot_path,
            }
            for s in sightings
        ],
    }


@router.post("/{code}/locate")
def locate(code: str, session: SessionDep):
    carton = get_carton_or_404(session, code)
    shelf_id = carton.last_seen_shelf_id or carton.dest_shelf_id
    shelf = session.get(Shelf, shelf_id)
    command = devices.queue_command(
        shelf.light_device_id if shelf else None, "blink", 30
    )
    return envelope(
        answer={
            "label_code": carton.label_code,
            "shelf": shelf.code if shelf else None,
            "level": shelf.level if shelf else None,
            "light_command": command,
        },
        confidence=1.0,
        sources=[f"carton:{carton.label_code}", f"shelf:{shelf.code if shelf else '?'}"],
        note="light queued" if command else "shelf has no light; virtual grid blinks",
    )
