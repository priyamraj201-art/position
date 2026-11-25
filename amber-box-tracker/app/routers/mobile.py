"""Mobile POV endpoints (PRD-02 section 2.2): live scan websocket,
proof-of-delivery upload, damage reports.

POV upload writes sightings BEFORE delivery_status is computed (alignment
decision). When Track 2's vision pipeline is not importable yet, proof is
still stored and the answer flags needs_human_review instead of guessing.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket
from sqlmodel import Session, select

from app import alerts
from app.db import SessionDep, get_engine
from app.main import BASE_DIR, envelope, get_settings
from app.models import Camera, Carton, Delivery, utcnow
from app.routers.cartons import normalize_code

router = APIRouter(tags=["mobile"])


def _pipeline():
    try:
        from app.vision import pipeline

        return pipeline
    except ImportError:
        return None


@router.websocket("/ws/pov")
async def pov_ws(websocket: WebSocket):
    await websocket.accept()
    pipeline = _pipeline()
    try:
        while True:
            frame = await websocket.receive_bytes()
            if pipeline is None:
                await websocket.send_json(
                    {"carton": None, "note": "vision pipeline not yet integrated"}
                )
                continue
            result = pipeline.decode_frame(frame, camera_id="CAM-POV")
            await websocket.send_json(result)
    except Exception:  # noqa: BLE001 - client disconnect ends the socket
        return


@router.post("/api/mobile/pov-upload/{delivery_id}")
async def pov_upload(
    delivery_id: str,
    session: SessionDep,
    file: Annotated[UploadFile, File(...)],
):
    delivery = session.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(404, f"unknown delivery: {delivery_id}")
    proof_dir = BASE_DIR / get_settings()["paths"]["proof"]
    proof_dir.mkdir(parents=True, exist_ok=True)
    path = proof_dir / f"{delivery_id}_{utcnow().strftime('%Y%m%dT%H%M%S')}.mp4"
    path.write_bytes(await file.read())
    delivery.proof_video_path = str(path.relative_to(BASE_DIR))
    session.add(delivery)
    session.commit()

    pipeline = _pipeline()
    if pipeline is None:
        return envelope(
            answer={"delivery_id": delivery_id, "proof": delivery.proof_video_path},
            confidence=0.0,
            sources=[f"delivery:{delivery_id}"],
            needs_human_review=True,
            note="proof stored; vision pipeline not yet integrated, cartons not scanned",
        )

    # Sightings first, status after (alignment decision).
    engine = get_engine()
    codes = pipeline.extract_label_codes(str(path))
    pov = session.get(Camera, "CAM-POV")
    with Session(engine) as write_session:
        from app.rules import record_sighting

        for code in codes:
            carton = write_session.exec(
                select(Carton).where(Carton.label_code == normalize_code(code))
            ).first()
            if carton is not None:
                record_sighting(write_session, carton, pov, source="phone")
    from app.routers.deliveries import delivery_status

    status = delivery_status(session, delivery)
    if status["missing"]:
        alerts.report_short_delivery(
            session, delivery_id, [{"label_code": c} for c in status["missing"]]
        )
    return envelope(
        answer=status,
        confidence=1.0,
        sources=[f"delivery:{delivery_id}", f"proof:{delivery.proof_video_path}"],
        needs_human_review=bool(status["missing"]),
        note="short delivery" if status["missing"] else "all expected cartons seen",
    )


@router.post("/api/mobile/damage")
async def damage(
    session: SessionDep,
    file: Annotated[UploadFile, File(...)],
    carton_code: str = Form(...),
    note: str = Form(...),
):
    carton = session.exec(
        select(Carton).where(Carton.label_code == normalize_code(carton_code))
    ).first()
    if carton is None:
        raise HTTPException(404, f"unknown carton: {carton_code}")
    snap_dir = BASE_DIR / get_settings()["paths"]["snapshots"]
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"damage_{carton.label_code}_{utcnow().strftime('%Y%m%dT%H%M%S')}.jpg"
    path.write_bytes(await file.read())
    rel = str(path.relative_to(BASE_DIR))
    issue, alert = alerts.report_damage(
        session, carton, note, evidence=[{"image": rel}], snapshot_path=rel
    )
    return envelope(
        answer={"issue_id": issue.id, "alert_id": alert.id, "carton": carton.label_code},
        confidence=1.0,
        sources=[f"carton:{carton.label_code}", f"snapshot:{rel}"],
        note="damage recorded",
    )
