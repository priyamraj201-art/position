"""Camera listing and MJPEG streams (PRD-02 section 2.2)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.db import SessionDep
from app.main import WORKERS
from app.models import Camera

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
def list_cameras(session: SessionDep):
    cameras = session.exec(select(Camera)).all()
    return {
        "cameras": [
            {
                "id": cam.id,
                "name": cam.name,
                "kind": cam.kind,
                "level": cam.level,
                "enabled": cam.enabled,
                "status": "live" if cam.id in WORKERS else "no_signal",
                "fps": getattr(WORKERS.get(cam.id), "fps", 0),
            }
            for cam in cameras
        ]
    }


@router.get("/{camera_id}/mjpeg")
async def mjpeg(camera_id: str, session: SessionDep):
    camera = session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, f"unknown camera: {camera_id}")
    worker = WORKERS.get(camera_id)
    if worker is None:
        raise HTTPException(503, f"camera {camera_id}: no_signal")

    async def stream():
        boundary = b"--frame\r\n"
        while True:
            jpeg = worker.latest_jpeg()
            if jpeg:
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(), media_type="multipart/x-mixed-replace; boundary=frame"
    )
