"""Deliveries: list, receive, confirm (PRD-02 section 2.2).

delivery_status derives from stored sightings only (architecture decision):
before POV ingestion every expected carton reads as missing.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app import alerts
from app.db import SessionDep
from app.models import Carton, Delivery, Sighting, utcnow

router = APIRouter(prefix="/api/deliveries", tags=["deliveries"])


class ConfirmBody(BaseModel):
    confirm: bool
    missing: list[str] | None = None  # label codes short on receipt


def delivery_status(session: Session, delivery: Delivery) -> dict:
    cartons = session.exec(
        select(Carton).where(Carton.delivery_id == delivery.id)
    ).all()
    seen = set()
    for carton in cartons:
        sighting = session.exec(
            select(Sighting).where(Sighting.carton_id == carton.id)
        ).first()
        if sighting is not None or carton.received_at is not None:
            seen.add(carton.label_code)
    expected = [c.label_code for c in cartons]
    missing = [code for code in expected if code not in seen]
    return {
        "id": delivery.id,
        "event_name": delivery.event_name,
        "status": delivery.status,
        "expected": expected,
        "seen": sorted(seen),
        "missing": missing,
        "proof_video_path": delivery.proof_video_path,
    }


@router.get("")
def list_deliveries(session: SessionDep):
    deliveries = session.exec(select(Delivery)).all()
    return {"deliveries": [delivery_status(session, d) for d in deliveries]}


@router.post("/{delivery_id}/receive")
def receive(delivery_id: str, session: SessionDep):
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(404, f"unknown delivery: {delivery_id}")
    now = utcnow()
    count = 0
    for carton in session.exec(
        select(Carton).where(Carton.delivery_id == delivery_id)
    ).all():
        if carton.received_at is None:
            carton.received_at = now
            carton.status = "received"
            session.add(carton)
            count += 1
    delivery.status = "received"
    session.add(delivery)
    session.commit()
    return {"id": delivery_id, "received": count, "received_at": now.isoformat()}


@router.post("/{delivery_id}/confirm")
def confirm(delivery_id: str, body: ConfirmBody, session: SessionDep):
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(404, f"unknown delivery: {delivery_id}")
    result: dict = {"id": delivery_id, "confirmed": body.confirm}
    if body.missing:
        issue, alert = alerts.report_short_delivery(
            session,
            delivery_id,
            [{"label_code": code} for code in body.missing],
        )
        result["short_delivery"] = {
            "issue_id": issue.id,
            "alert_id": alert.id,
            "missing": body.missing,
        }
    delivery.status = "confirmed"
    session.add(delivery)
    session.commit()
    return result
