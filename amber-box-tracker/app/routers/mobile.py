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
from app.models import Camera, Carton, Delivery, Shelf, utcnow
from app.routers.cartons import normalize_code

router = APIRouter(tags=["mobile"])


_decoder = None


def _qr_decoder():
    """Shared Track-2 QRDecoder (lazy: cv2 is optional outside vision runs)."""
    global _decoder
    if _decoder is None:
        try:
            from app.vision.qr import QRDecoder
        except ImportError:
            return None
        _decoder = QRDecoder(wechat_dir=BASE_DIR / "models" / "wechat")
    return _decoder


def _extract_label_codes(video_path: str, max_frames: int = 30) -> list[str] | None:
    """Sample a POV clip and decode KYC1 carton codes via Track 2's QRDecoder.

    Returns None when vision deps are unavailable, otherwise the sorted unique
    bare codes found (possibly empty).
    """
    try:
        import cv2
    except ImportError:
        return None
    decoder = _qr_decoder()
    if decoder is None:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    codes: set[str] = set()
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    step = max(1, total // max_frames)
    idx = 0
    frames_read = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            frames_read += 1
            for qr in decoder.decode_full_frame(frame):
                codes.add(normalize_code(qr.code))
        idx += 1
    cap.release()
    # An unreadable clip is not evidence of a short delivery: report not-scanned.
    if frames_read == 0:
        return None
    return sorted(codes)


def _decode_pov_frame(frame_bytes: bytes) -> dict:
    """Live POV scan: decode one JPEG/PNG frame, answer where the carton goes."""
    decoder = _qr_decoder()
    if decoder is None:
        return {"carton": None, "note": "vision pipeline not yet integrated"}
    try:
        import cv2
        import numpy as np

        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
    except ImportError:
        return {"carton": None, "note": "vision pipeline not yet integrated"}
    if frame is None:
        return {"carton": None, "note": "could not decode frame"}
    codes = [normalize_code(qr.code) for qr in decoder.decode_full_frame(frame)]
    if not codes:
        return {"carton": None, "note": "no label found"}
    code = codes[0]
    with Session(get_engine()) as session:
        carton = session.exec(select(Carton).where(Carton.label_code == code)).first()
        if carton is None:
            return {"carton": code, "note": "unknown carton"}
        shelf = session.get(Shelf, carton.dest_shelf_id)
        return {
            "carton": code,
            "item_name": carton.item_name,
            "dest_level": carton.dest_level,
            "dest_shelf": shelf.code if shelf else None,
        }


@router.websocket("/ws/pov")
async def pov_ws(websocket: WebSocket):
    await websocket.accept()
    while True:
        try:
            frame = await websocket.receive_bytes()
        except Exception:  # noqa: BLE001 - client disconnect ends the socket
            return
        from app.main import WORKERS
        from app.vision.sources import PushSource

        pov_worker = WORKERS.get("CAM-POV")
        if pov_worker is not None and isinstance(getattr(pov_worker, "source", None), PushSource):
            pov_worker.source.push_jpeg(frame)
        await websocket.send_json(_decode_pov_frame(frame))


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

    codes = _extract_label_codes(str(path))
    if codes is None:
        return envelope(
            answer={"delivery_id": delivery_id, "proof": delivery.proof_video_path},
            confidence=0.0,
            sources=[f"delivery:{delivery_id}"],
            needs_human_review=True,
            note="proof stored; cartons not scanned (vision unavailable or unreadable video)",
        )

    # Sightings first, status after (alignment decision).
    engine = get_engine()
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
