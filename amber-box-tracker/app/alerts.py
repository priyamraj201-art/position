"""Alert creation, dedup, resolution and SSE broadcast (PRD-02 section 2.1).

Dedup rule: at most one OPEN alert per (carton_id, type). Every new or
resolved alert is published to the broadcaster for the SSE stream.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlmodel import Session, select

from app.models import Alert, Carton, DeliveryIssue, Shelf

ALERT_TYPES = {"wrong_floor", "wrong_shelf", "not_arrived", "short_delivery", "damaged"}


class AlertBroadcaster:
    """Fan-out of alert events to SSE subscribers (asyncio queues)."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow consumer drops events, never blocks the app


broadcaster = AlertBroadcaster()


def alert_payload(alert: Alert, shelf_light_events: list[dict] | None = None) -> dict:
    return {
        "id": alert.id,
        "type": alert.type,
        "message": alert.message,
        "carton_id": alert.carton_id,
        "snapshot_path": alert.snapshot_path,
        "created_at": alert.created_at.isoformat(),
        "shelf_light_events": shelf_light_events or [],
    }


def open_alert_for(
    session: Session,
    carton_id: int | None,
    alert_type: str,
    delivery_id: str | None = None,
) -> Alert | None:
    """The one open alert for the dedup key: (carton_id, type), or
    (delivery_id, type) for delivery-scoped alerts without a carton."""
    query = select(Alert).where(Alert.type == alert_type, Alert.status == "open")
    if carton_id is not None:
        query = query.where(Alert.carton_id == carton_id)
    elif delivery_id is not None:
        query = query.where(Alert.delivery_id == delivery_id)
    else:
        return None
    return session.exec(query).first()


def create_alert(
    session: Session,
    alert_type: str,
    message: str,
    carton_id: int | None = None,
    delivery_id: str | None = None,
    camera_id: str | None = None,
    snapshot_path: str | None = None,
    shelf_light_events: list[dict] | None = None,
    publish: bool = True,
) -> tuple[Alert, bool]:
    """Create an alert with dedup. Returns (alert, created)."""
    if alert_type not in ALERT_TYPES:
        raise ValueError(f"unknown alert type: {alert_type}")
    if carton_id is not None or delivery_id is not None:
        existing = open_alert_for(session, carton_id, alert_type, delivery_id)
        if existing is not None:
            return existing, False
    alert = Alert(
        type=alert_type,
        message=message,
        carton_id=carton_id,
        delivery_id=delivery_id,
        camera_id=camera_id,
        snapshot_path=snapshot_path,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    if publish:
        broadcaster.publish(alert_payload(alert, shelf_light_events))
    return alert, True


def resolve_alert(
    session: Session,
    alert_id: int,
    note: str,
    new_dest_shelf_id: int | None = None,
    publish: bool = True,
) -> Alert | None:
    """Resolve an alert; optionally repoint the carton's destination shelf."""
    alert = session.get(Alert, alert_id)
    if alert is None:
        return None
    if alert.status == "resolved":
        return alert  # idempotent: never overwrite the note or republish
    alert.status = "resolved"
    alert.resolved_note = note
    if new_dest_shelf_id is not None and alert.carton_id is not None:
        carton = session.get(Carton, alert.carton_id)
        shelf = session.get(Shelf, new_dest_shelf_id)
        if carton is not None and shelf is not None:
            carton.dest_shelf_id = shelf.id
            carton.dest_level = shelf.level
            carton.dest_facility_id = shelf.facility_id
            session.add(carton)
    session.add(alert)
    session.commit()
    session.refresh(alert)
    if publish:
        payload = alert_payload(alert)
        payload["status"] = "resolved"
        payload["resolved_note"] = note
        broadcaster.publish(payload)
    return alert


def auto_resolve_for_carton(
    session: Session,
    carton_id: int,
    types: tuple[str, ...] = ("wrong_floor", "wrong_shelf"),
    note: str = "auto-resolved",
) -> int:
    """Resolve open alerts of the given types for a carton. Returns count."""
    count = 0
    for alert_type in types:
        alert = open_alert_for(session, carton_id, alert_type)
        if alert is not None:
            resolve_alert(session, alert.id, note)
            count += 1
    return count


def report_damage(
    session: Session,
    carton: Carton,
    note: str,
    evidence: list[dict] | None = None,
    snapshot_path: str | None = None,
    publish: bool = True,
) -> tuple[DeliveryIssue, Alert]:
    """Track 1 owns DeliveryIssue (PRD-01 1.3): record the damaged item and
    raise the paired `damaged` alert atomically. Callers: mobile damage
    endpoint and Amber's report_damage tool (after its confirm step).

    Idempotent per report: an identical report (same carton, same note)
    returns the existing issue row instead of duplicating - a Confirm
    retried by the UI or a tool replay is safe. A genuinely new damage
    report has a different note and records a new row.
    """
    for issue in session.exec(
        select(DeliveryIssue).where(DeliveryIssue.delivery_id == carton.delivery_id)
    ).all():
        for existing in issue.damaged_items:
            if existing.get("label_code") == carton.label_code and existing.get("note") == note:
                alert, _ = create_alert(
                    session,
                    "damaged",
                    f"Box {carton.label_code} ({carton.item_name}) reported damaged: {note}",
                    carton_id=carton.id,
                    delivery_id=carton.delivery_id,
                    snapshot_path=snapshot_path,
                    publish=publish,
                )
                return issue, alert
    item: dict[str, Any] = {"label_code": carton.label_code, "note": note}
    if snapshot_path:
        item["snapshot_path"] = snapshot_path
    issue = DeliveryIssue(
        delivery_id=carton.delivery_id,
        damaged_items=[item],
        evidence=evidence or [],
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    alert, _ = create_alert(
        session,
        "damaged",
        f"Box {carton.label_code} ({carton.item_name}) reported damaged: {note}",
        carton_id=carton.id,
        delivery_id=carton.delivery_id,
        snapshot_path=snapshot_path,
        publish=publish,
    )
    return issue, alert


def report_short_delivery(
    session: Session,
    delivery_id: str,
    missing_items: list[dict],
    wrong_items: list[dict] | None = None,
    evidence: list[dict] | None = None,
    publish: bool = True,
) -> tuple[DeliveryIssue, Alert]:
    """Record a short delivery (POV proof-of-delivery found fewer cartons
    than expected) and raise the paired `short_delivery` alert. Deduped
    per (delivery_id, type) so re-uploads don't spam the dashboard."""
    issue = DeliveryIssue(
        delivery_id=delivery_id,
        missing_items=missing_items,
        wrong_items=wrong_items or [],
        evidence=evidence or [],
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)
    codes = ", ".join(str(i.get("label_code", "?")) for i in missing_items)
    alert, _ = create_alert(
        session,
        "short_delivery",
        f"Delivery {delivery_id} is short: missing {codes}.",
        delivery_id=delivery_id,
        publish=publish,
    )
    return issue, alert


def list_alerts(
    session: Session,
    alert_type: str | None = None,
    status: str | None = None,
) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc())
    if alert_type:
        query = query.where(Alert.type == alert_type)
    if status:
        query = query.where(Alert.status == status)
    return list(session.exec(query).all())
