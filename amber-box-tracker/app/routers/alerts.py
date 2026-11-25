"""Alert list, SSE stream and resolution (PRD-02 section 2.2)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import alerts as alert_service
from app.db import SessionDep

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class ResolveBody(BaseModel):
    note: str
    new_dest_shelf_id: int | None = None


@router.get("")
def list_alerts(
    session: SessionDep,
    type: str | None = None,
    status: str | None = None,
):
    found = alert_service.list_alerts(session, alert_type=type, status=status)
    return {"alerts": [alert_service.alert_payload(a) | {"status": a.status} for a in found]}


@router.get("/stream")
async def stream():
    queue = alert_service.broadcaster.subscribe()

    async def events():
        try:
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            alert_service.broadcaster.unsubscribe(queue)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{alert_id}/resolve")
def resolve(alert_id: int, body: ResolveBody, session: SessionDep):
    alert = alert_service.resolve_alert(
        session, alert_id, body.note, new_dest_shelf_id=body.new_dest_shelf_id
    )
    if alert is None:
        raise HTTPException(404, f"unknown alert: {alert_id}")
    return alert_service.alert_payload(alert) | {"status": alert.status}
