"""Load data/seed.json into an empty database (PRD-01 section 1.4)."""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from app import models

BASE_DIR = Path(__file__).resolve().parent.parent
SEED_PATH = BASE_DIR / "data" / "seed.json"


def seed_if_empty(session: Session, seed_path: Path | str | None = None) -> bool:
    """Load the seed when the database has no project yet.

    Returns True when the seed was loaded, False when data already existed.
    """
    existing = session.exec(select(models.Project)).first()
    if existing is not None:
        return False

    path = Path(seed_path) if seed_path else SEED_PATH
    data = json.loads(path.read_text(encoding="utf-8"))

    project = models.Project(name=data["project"]["name"])
    session.add(project)
    session.flush()

    facilities: dict[str, models.StorageFacility] = {}
    for row in data["facilities"]:
        facility = models.StorageFacility(
            project_id=project.id, name=row["name"], level=row["level"]
        )
        session.add(facility)
        session.flush()
        facilities[facility.name] = facility

    shelves: dict[str, models.Shelf] = {}
    for row in data["shelves"]:
        shelf = models.Shelf(
            facility_id=facilities[row["facility"]].id,
            level=row["level"],
            code=row["code"],
            marker_id=row["marker_id"],
            light_device_id=row["light_device_id"],
        )
        session.add(shelf)
        session.flush()
        shelves[shelf.code] = shelf

    for row in data["purchase_orders"]:
        session.add(
            models.PurchaseOrder(
                po_number=row["po_number"], supplier=row["supplier"], lines=row["lines"]
            )
        )

    for row in data["deliveries"]:
        session.add(
            models.Delivery(
                id=row["id"],
                event_name=row["event_name"],
                po_ids=row["po_ids"],
                gate=row["gate"],
                storage_facility_id=facilities[row["facility"]].id,
                date=row["date"],
                status=row["status"],
            )
        )

    for row in data["cartons"]:
        dest = shelves[row["dest_shelf"]]
        session.add(
            models.Carton(
                label_code=row["label_code"],
                delivery_id=row["delivery_id"],
                po_number=row["po_number"],
                po_line=row["po_line"],
                part_number=row["part_number"],
                item_name=row["item_name"],
                qty_in_carton=row["qty_in_carton"],
                dest_facility_id=dest.facility_id,
                dest_level=dest.level,
                dest_shelf_id=dest.id,
            )
        )

    for row in data["cameras"]:
        facility_name = row["facility"]
        session.add(
            models.Camera(
                id=row["id"],
                name=row["name"],
                kind=row["kind"],
                level=row["level"],
                facility_id=facilities[facility_name].id if facility_name else None,
                source=row["source"],
                enabled=row["enabled"],
            )
        )

    for row in data["shelf_lights"]:
        session.add(
            models.ShelfLight(
                device_id=row["device_id"], shelf_id=shelves[row["shelf"]].id
            )
        )

    session.commit()
    return True
