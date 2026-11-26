"""Shelf-light device channel: command queue + long-poll (PRD-02 section 2.3).

Commands are held in-process (per-device deque) and delivered when the ESP32
(or sim.py) long-polls GET /api/devices/{id}/commands. Telemetry
(last_seen, battery, rssi) persists on the ShelfLight row.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any

from sqlmodel import Session, select

from app.models import Shelf, ShelfLight, utcnow

COMMAND_COLORS: dict[str, str | None] = {
    "blink": "blue",
    "blink_red": "red",
    "ack": "green",
    "off": None,
}

MAX_WAIT_SECONDS = 25

_queues: dict[str, deque] = defaultdict(deque)
_events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)


def reset() -> None:
    """Clear all queues and waiters (tests)."""
    _queues.clear()
    _events.clear()


def queue_command(device_id: str | None, cmd: str, seconds: int) -> dict | None:
    """Queue a command for a device. Returns the command, or None if the
    device id is missing (shelf without a light)."""
    if cmd not in COMMAND_COLORS:
        raise ValueError(f"unknown command: {cmd}")
    if not device_id:
        return None
    command: dict[str, Any] = {"cmd": cmd, "color": COMMAND_COLORS[cmd], "seconds": seconds}
    _queues[device_id].append(command)
    _events[device_id].set()
    return command


def pending_commands(device_id: str) -> list[dict]:
    return list(_queues.get(device_id, ()))


def _drain(device_id: str) -> list[dict]:
    commands = list(_queues.get(device_id, ()))
    if device_id in _queues:
        _queues[device_id].clear()
    _events[device_id].clear()
    return commands


def update_telemetry(
    session: Session,
    device_id: str,
    battery: float | None = None,
    rssi: int | None = None,
) -> ShelfLight | None:
    light = session.exec(
        select(ShelfLight).where(ShelfLight.device_id == device_id)
    ).first()
    if light is None:
        return None
    light.last_seen = utcnow()
    if battery is not None:
        light.battery = battery
    if rssi is not None:
        light.rssi = rssi
    session.add(light)
    session.commit()
    session.refresh(light)
    return light


async def wait_commands(
    session: Session,
    device_id: str,
    wait: float = 0,
    battery: float | None = None,
    rssi: int | None = None,
) -> list[dict]:
    """Long-poll for queued commands, up to min(wait, MAX_WAIT_SECONDS)."""
    update_telemetry(session, device_id, battery, rssi)
    wait = max(0.0, min(float(wait), float(MAX_WAIT_SECONDS)))
    if _queues.get(device_id):
        return _drain(device_id)
    if wait <= 0:
        return []
    event = _events[device_id]
    event.clear()
    deadline = time.monotonic() + wait
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(event.wait(), timeout=remaining)
        except asyncio.TimeoutError:  # noqa: UP041 - builtin alias only exists on 3.11+; 3.10 raises this one
            break
        if _queues.get(device_id):
            return _drain(device_id)
        event.clear()
    return _drain(device_id)


def grid_state(session: Session) -> dict[str, Any]:
    """Virtual shelf grid: pending command per shelf for the dashboard."""
    cells: dict[str, Any] = {}
    for light in session.exec(select(ShelfLight)).all():
        shelf = session.get(Shelf, light.shelf_id)
        if shelf is None:
            continue
        pending = pending_commands(light.device_id)
        cells[shelf.code] = {
            "device_id": light.device_id,
            "last_seen": light.last_seen.isoformat() if light.last_seen else None,
            "battery": light.battery,
            "rssi": light.rssi,
            "active": pending[0] if pending else None,
        }
    return {"shelves": cells}
