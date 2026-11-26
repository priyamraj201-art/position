"""Canonical data model for Amber Box Tracker (PRD-01 section 1.3).

SQLModel tables mirror Kaya's production shapes (delivery_details,
purchase_order, storage_facility, delivery_issues) for easy porting.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

# All timestamps are naive UTC by convention: annotate with pydantic's
# NaiveDatetime so sqlmodel >= 0.0.49 maps them to naive DateTime columns
# (its default datetime mapping enforces timezone-aware values, which
# SQLite round-trips inconsistently).


QR_PREFIX = "KYC1:"


def strip_qr_prefix(code: str) -> str:
    """Boundary rule: QR payloads are KYC1:<6 chars>; stored labels are bare."""
    return code.strip().upper().removeprefix(QR_PREFIX)


def utcnow() -> datetime:
    """Naive UTC now - every app timestamp is naive UTC by convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017 - py310-safe


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class StorageFacility(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    level: int


class Shelf(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    facility_id: int = Field(foreign_key="storagefacility.id")
    level: int
    code: str = Field(unique=True, index=True)
    marker_id: int = Field(unique=True)
    light_device_id: str | None = None


class PurchaseOrder(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    po_number: str = Field(unique=True, index=True)
    supplier: str
    lines: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))


class Delivery(SQLModel, table=True):
    id: str = Field(primary_key=True)  # e.g. "DEL-2211"
    event_name: str
    po_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    gate: str
    storage_facility_id: int = Field(foreign_key="storagefacility.id")
    date: str
    status: str = "expected"  # expected | receiving | received | confirmed
    proof_video_path: str | None = None


class Carton(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    label_code: str = Field(unique=True, index=True)  # 6-char code from KYC1:<code>
    delivery_id: str = Field(foreign_key="delivery.id")
    po_number: str
    po_line: int
    part_number: str
    item_name: str
    qty_in_carton: int
    dest_facility_id: int = Field(foreign_key="storagefacility.id")
    dest_level: int
    dest_shelf_id: int = Field(foreign_key="shelf.id")
    status: str = "received"  # received | in_transit | stored | misplaced | issued
    received_at: NaiveDatetime | None = None
    last_seen_at: NaiveDatetime | None = None
    last_seen_level: int | None = None
    last_seen_shelf_id: int | None = Field(default=None, foreign_key="shelf.id")
    last_seen_camera_id: str | None = Field(default=None, foreign_key="camera.id")
    last_snapshot: str | None = None


class Camera(SQLModel, table=True):
    id: str = Field(primary_key=True)  # e.g. "CAM-GATE"
    name: str
    kind: str  # gate | hoist | floor_entrance | aisle | pov
    level: int | None = None
    facility_id: int | None = Field(default=None, foreign_key="storagefacility.id")
    source: str = "file"
    enabled: bool = True


class Sighting(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    carton_id: int = Field(foreign_key="carton.id")
    camera_id: str = Field(foreign_key="camera.id")
    source: str = "cctv"  # cctv | phone | glasses
    level: int | None = None
    shelf_id: int | None = Field(default=None, foreign_key="shelf.id")
    seen_at: NaiveDatetime = Field(default_factory=utcnow)
    snapshot_path: str | None = None
    bbox: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    track_id: int | None = None


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str  # wrong_floor | wrong_shelf | not_arrived | short_delivery | damaged
    carton_id: int | None = Field(default=None, foreign_key="carton.id")
    delivery_id: str | None = Field(default=None, foreign_key="delivery.id")
    camera_id: str | None = Field(default=None, foreign_key="camera.id")
    message: str
    snapshot_path: str | None = None
    status: str = "open"  # open | resolved
    created_at: NaiveDatetime = Field(default_factory=utcnow)
    resolved_note: str | None = None


class DeliveryIssue(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    delivery_id: str = Field(foreign_key="delivery.id")
    missing_items: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    wrong_items: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    damaged_items: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    evidence: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class ShelfLight(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(unique=True, index=True)  # e.g. "shelf-light-01"
    shelf_id: int = Field(foreign_key="shelf.id")
    last_seen: NaiveDatetime | None = None
    battery: float | None = None
    rssi: int | None = None
