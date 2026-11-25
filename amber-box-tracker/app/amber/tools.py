"""Amber tool functions. Pure logic over an `AmberStore`, so the data layer can be swapped."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any, Protocol

FUZZY_THRESHOLD = 0.6
MAX_MATCHES = 5


@dataclass(frozen=True)
class CartonView:
    label_code: str
    po_number: str
    part_number: str
    item_name: str
    status: str
    delivery_id: str | None
    dest_level: int
    dest_shelf_code: str
    last_seen_level: int | None = None
    last_seen_shelf_code: str | None = None


@dataclass(frozen=True)
class DeliveryView:
    delivery_id: str
    expected_codes: tuple[str, ...]
    seen_codes: tuple[str, ...]


@dataclass(frozen=True)
class AlertView:
    id: int
    type: str
    message: str
    carton_code: str | None = None


class AmberStore(Protocol):
    """What the tools need from the data layer. Track 1's models implement this."""

    def list_cartons(self) -> list[CartonView]: ...
    def get_carton(self, code: str) -> CartonView | None: ...
    def get_delivery(self, delivery_id: str) -> DeliveryView | None: ...
    def open_alerts(self) -> list[AlertView]: ...
    def locate(self, code: str) -> dict[str, Any]: ...
    def create_damage(self, code: str, note: str) -> int: ...
    def resolve_alert(self, alert_id: int, note: str) -> bool: ...


def normalize_code(text: str) -> str:
    """Upper-case a label code and add the KYC1: prefix when only the 6 chars are given."""
    value = text.strip().upper()
    if len(value) == 6 and value.isalnum():
        return f"KYC1:{value}"
    return value


def _score(query: str, carton: CartonView) -> float:
    q = query.strip().lower()
    best = 0.0
    for field in (carton.label_code, carton.part_number, carton.item_name, carton.po_number):
        f = field.lower()
        if q in f:
            best = max(best, 1.0)
        else:
            best = max(best, difflib.SequenceMatcher(None, q, f).ratio())
            for word in f.split():
                best = max(best, difflib.SequenceMatcher(None, q, word).ratio())
    return best


def _where(c: CartonView) -> str:
    return f"Floor {c.dest_level}, shelf {c.dest_shelf_code}"


def summarize(c: CartonView, score: float = 1.0) -> dict[str, Any]:
    out: dict[str, Any] = {
        "score": round(score, 2),
        "label_code": c.label_code,
        "item_name": c.item_name,
        "po_number": c.po_number,
        "status": c.status,
        "belongs_at": _where(c),
    }
    if c.last_seen_level is not None:
        shelf = f", shelf {c.last_seen_shelf_code}" if c.last_seen_shelf_code else ""
        out["last_seen"] = f"Floor {c.last_seen_level}{shelf}"
    return out


def find_carton(store: AmberStore, query: str, auto_locate: bool = False) -> dict[str, Any]:
    """Fuzzy search cartons; with auto_locate, also light the shelf of the best match."""
    scored = sorted(((_score(query, c), c) for c in store.list_cartons()), key=lambda s: -s[0])
    hits = [(s, c) for s, c in scored if s >= FUZZY_THRESHOLD][:MAX_MATCHES]
    exact = [(s, c) for s, c in hits if c.label_code == normalize_code(query)]
    if exact:  # a full label code names one carton, drop look-alike codes
        hits = exact
    result: dict[str, Any] = {"query": query, "matches": [summarize(c, s) for s, c in hits]}
    if auto_locate and hits:
        result["locate"] = store.locate(hits[0][1].label_code)
    return result


def where_does_this_go(store: AmberStore, carton_code: str) -> dict[str, Any]:
    carton = store.get_carton(normalize_code(carton_code))
    if carton is None:
        return {"found": False, "carton_code": carton_code}
    return {"found": True, "carton_code": carton.label_code, "item_name": carton.item_name,
            "destination": _where(carton)}


def delivery_status(store: AmberStore, delivery_id: str) -> dict[str, Any]:
    delivery = store.get_delivery(delivery_id.strip().upper())
    if delivery is None:
        return {"found": False, "delivery_id": delivery_id}
    seen = set(delivery.seen_codes)
    missing = [c for c in delivery.expected_codes if c not in seen]
    return {"found": True, "delivery_id": delivery.delivery_id,
            "expected": len(delivery.expected_codes),
            "seen": len(seen & set(delivery.expected_codes)), "missing_codes": missing}


def report_damage(store: AmberStore, carton_code: str, note: str,
                  confirm: bool = False) -> dict[str, Any]:
    """Two-step: without confirm only asks; with confirm records the damage."""
    carton = store.get_carton(normalize_code(carton_code))
    if carton is None:
        return {"found": False, "carton_code": carton_code}
    if not confirm:
        return {"needs_confirmation": True,
                "prompt": f"Confirm marking {carton.label_code} ({carton.item_name}) as damaged?"}
    alert_id = store.create_damage(carton.label_code, note)
    return {"recorded": True, "carton_code": carton.label_code, "alert_id": alert_id}


def list_open_alerts(store: AmberStore) -> dict[str, Any]:
    alerts = store.open_alerts()
    return {"count": len(alerts),
            "alerts": [{"id": a.id, "type": a.type, "message": a.message} for a in alerts]}


def resolve_alert(store: AmberStore, alert_id: int, note: str) -> dict[str, Any]:
    """Close an alert. A human note is required, an empty note is refused."""
    if not note.strip():
        return {"resolved": False, "error": "A human note is required to resolve an alert."}
    return {"resolved": store.resolve_alert(alert_id, note.strip()), "alert_id": alert_id}
