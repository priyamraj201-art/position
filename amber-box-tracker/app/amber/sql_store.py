"""AmberStore over the app's SQLModel tables (Track 1's models.py / db.py).

Label codes: the database keeps the bare 6 characters (`BV2401`). Amber and MCP show and accept the
QR form `KYC1:BV2401`, so this class adds and strips the prefix at the edge.

Timestamps follow Track 1's convention: naive UTC (`datetime.utcnow()`).
Alerts go through `app.alerts` (dedup, SSE) and lights through `app.devices.queue_command`.
Both keep state in process memory (SSE subscribers, light queue), so this store only reaches the
running app's lights and SSE stream when it runs inside the app process.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app import alerts, devices, models
from app.amber.tools import AlertView, CartonView, DeliveryView

PREFIX = "KYC1:"
LOCATE_SECONDS = 30


def _bare(code: str) -> str:
    code = code.strip().upper()
    return code.removeprefix(PREFIX)


class SqlAmberStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _shelf_codes(session: Session) -> dict[int | None, str]:
        return {s.id: s.code for s in session.exec(select(models.Shelf))}

    @staticmethod
    def _view(c: models.Carton, shelves: dict[int | None, str]) -> CartonView:
        return CartonView(
            label_code=PREFIX + c.label_code, po_number=c.po_number, part_number=c.part_number,
            item_name=c.item_name, status=c.status, delivery_id=c.delivery_id,
            dest_level=c.dest_level, dest_shelf_code=shelves.get(c.dest_shelf_id, "?"),
            last_seen_level=c.last_seen_level,
            last_seen_shelf_code=shelves.get(c.last_seen_shelf_id))

    def list_cartons(self) -> list[CartonView]:
        with Session(self._engine) as s:
            shelves = self._shelf_codes(s)
            return [self._view(c, shelves) for c in s.exec(select(models.Carton))]

    def get_carton(self, code: str) -> CartonView | None:
        with Session(self._engine) as s:
            c = s.exec(select(models.Carton).where(models.Carton.label_code == _bare(code))).first()
            return self._view(c, self._shelf_codes(s)) if c else None

    def get_delivery(self, delivery_id: str) -> DeliveryView | None:
        with Session(self._engine) as s:
            if s.get(models.Delivery, delivery_id) is None:
                return None
            cartons = s.exec(select(models.Carton).where(
                models.Carton.delivery_id == delivery_id).order_by(models.Carton.id)).all()
            seen_ids = set(s.exec(select(models.Sighting.carton_id).distinct()))
            return DeliveryView(
                delivery_id,
                tuple(PREFIX + c.label_code for c in cartons),
                tuple(PREFIX + c.label_code for c in cartons
                      if c.id in seen_ids or c.received_at is not None))

    def open_alerts(self) -> list[AlertView]:
        with Session(self._engine) as s:
            codes = {c.id: c.label_code for c in s.exec(select(models.Carton))}
            rows = s.exec(select(models.Alert).where(models.Alert.status == "open")
                          .order_by(models.Alert.id)).all()
            return [AlertView(a.id or 0, a.type, a.message,
                              PREFIX + codes[a.carton_id] if a.carton_id in codes else None)
                    for a in rows]

    def locate(self, code: str) -> dict[str, Any]:
        """Blink the shelf light of the carton's current shelf, else its destination shelf."""
        with Session(self._engine) as s:
            c = s.exec(select(models.Carton).where(models.Carton.label_code == _bare(code))).first()
            if c is None:
                return {"queued": False, "error": "unknown carton"}
            shelf = s.get(models.Shelf, c.last_seen_shelf_id or c.dest_shelf_id)
            device = shelf.light_device_id if shelf else None
            command = devices.queue_command(device, "blink", LOCATE_SECONDS)
            return {"queued": command is not None, "shelf": shelf.code if shelf else None,
                    "device_id": device, "command": command}

    def create_damage(self, code: str, note: str) -> int:
        """Record a confirmed damage report through Track 1's alerts.report_damage.

        It is idempotent for the same carton and note, so a repeated Confirm is safe."""
        with Session(self._engine) as s:
            c = s.exec(select(models.Carton).where(models.Carton.label_code == _bare(code))).one()
            _, alert = alerts.report_damage(s, c, note)
            return alert.id or 0

    def resolve_alert(self, alert_id: int, note: str) -> bool:
        """True only when this call closed an open alert (alerts.resolve_alert is idempotent)."""
        with Session(self._engine) as s:
            current = s.get(models.Alert, alert_id)
            if current is None or current.status != "open":
                return False
            return alerts.resolve_alert(s, alert_id, note) is not None
