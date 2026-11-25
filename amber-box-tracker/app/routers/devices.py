"""Shelf-light device endpoints (PRD-02 section 2.3)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import devices
from app.db import SessionDep

router = APIRouter(prefix="/api/devices", tags=["devices"])


class HeartbeatBody(BaseModel):
    battery: float | None = None
    rssi: int | None = None


@router.get("/grid-state")
def grid_state(session: SessionDep):
    return devices.grid_state(session)


@router.get("/{device_id}/commands")
async def commands(
    session: SessionDep,
    device_id: str,
    wait: float = 0,
    battery: float | None = None,
    rssi: int | None = None,
):
    found = await devices.wait_commands(
        session, device_id, wait=wait, battery=battery, rssi=rssi
    )
    return {"commands": found}


@router.post("/{device_id}/heartbeat")
def heartbeat(device_id: str, body: HeartbeatBody, session: SessionDep):
    light = devices.update_telemetry(session, device_id, body.battery, body.rssi)
    if light is None:
        return {"ok": False, "note": f"unknown device: {device_id}"}
    return {"ok": True}
