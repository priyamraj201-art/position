"""Per-camera background worker threads: drop-oldest-frame grabber, VisionPipeline, MJPEG & DB."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlmodel import Session, select

from app.models import Camera, Carton, Shelf, utcnow
from app.rules import record_sighting
from app.vision.pipeline import CameraContext, VisionPipeline
from app.vision.sources import FrameSource, PushSource, build_source

log = logging.getLogger("amber.vision.worker")
BASE_DIR = Path(__file__).resolve().parents[2]


class CameraWorker:
    """Runs a single camera's frame grabber + VisionPipeline in background threads."""

    def __init__(
        self,
        cam_cfg: dict[str, Any],
        engine: Any,
        pipeline_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.camera_id: str = cam_cfg["id"]
        self.fps_process: float = float(cam_cfg.get("fps_process", 5))
        self.loop: bool = bool(cam_cfg.get("loop", True))
        self.engine = engine

        raw_source = str(cam_cfg.get("source", ""))
        source_type = cam_cfg.get("source_type", "")
        if source_type == "file" and not raw_source.startswith("file:"):
            raw_source = f"file:{BASE_DIR / raw_source}"
        elif raw_source.startswith("file:"):
            rel = raw_source[len("file:") :]
            p = Path(rel)
            if not p.is_absolute():
                raw_source = f"file:{BASE_DIR / p}"

        self.source: FrameSource = build_source(raw_source, loop=self.loop)
        self.fps: float = 0.0

        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_raw: np.ndarray | None = None
        self._jpeg_lock = threading.Lock()
        self._latest_jpeg_bytes: bytes | None = None

        self._pipeline_kwargs = pipeline_kwargs or {}
        self._grab_thread = threading.Thread(
            target=self._grab_loop, name=f"grab-{self.camera_id}", daemon=True
        )
        self._proc_thread = threading.Thread(
            target=self._process_loop, name=f"proc-{self.camera_id}", daemon=True
        )

    def start(self) -> None:
        if self.source.status == "no_signal":
            return
        if not isinstance(self.source, PushSource):
            self._grab_thread.start()
        self._proc_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.source.close()

    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._latest_jpeg_bytes

    def _grab_loop(self) -> None:
        """Continuously read frames and overwrite the single-slot buffer (drop old frames)."""
        while not self._stop.is_set():
            frame = self.source.read()
            if frame is None:
                time.sleep(0.1)
                continue
            with self._frame_lock:
                self._latest_raw = frame

    def _load_context(self) -> tuple[CameraContext, dict[int, str], dict[str, dict[str, Any]], dict[str, int]]:
        with Session(self.engine) as session:
            cam = session.get(Camera, self.camera_id)
            ctx = CameraContext(
                id=self.camera_id,
                name=cam.name if cam else self.camera_id,
                kind=cam.kind if cam else "gate",
                level=cam.level if cam else None,
                facility_id=cam.facility_id if cam else None,
            )
            shelves = session.exec(select(Shelf)).all()
            marker_to_shelf = {s.marker_id: s.code for s in shelves}
            shelf_code_to_id = {s.code: s.id for s in shelves}
            shelf_id_to_code = {s.id: s.code for s in shelves}

            cartons = session.exec(select(Carton)).all()
            carton_dests = {
                c.label_code: {
                    "dest_level": c.dest_level,
                    "dest_shelf": shelf_id_to_code.get(c.dest_shelf_id, "?"),
                }
                for c in cartons
            }
            return ctx, marker_to_shelf, carton_dests, shelf_code_to_id

    def _process_loop(self) -> None:
        ctx, marker_to_shelf, carton_dests, shelf_code_to_id = self._load_context()
        # Use detector='none' for non-aisle cameras by default if CPU budget is tight,
        # or honor pipeline_kwargs['detector_mode'] when passed.
        pipeline = VisionPipeline(
            marker_to_shelf=marker_to_shelf,
            carton_destinations=carton_dests,
            **self._pipeline_kwargs,
        )
        interval = 1.0 / max(self.fps_process, 1.0)

        while not self._stop.is_set():
            t0 = time.perf_counter()
            if isinstance(self.source, PushSource):
                frame = self.source.read()
            else:
                with self._frame_lock:
                    frame = self._latest_raw
                    self._latest_raw = None

            if frame is None:
                time.sleep(0.05)
                continue

            res = pipeline.process_frame(frame, ctx, save_snapshots=True)
            self.fps = round(res.fps, 2)

            ok, buf = cv2.imencode(".jpg", res.annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self._jpeg_lock:
                    self._latest_jpeg_bytes = buf.tobytes()

            if res.sightings:
                self._persist_sightings(res.sightings, shelf_code_to_id)

            elapsed = time.perf_counter() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)

    def _persist_sightings(self, sightings: list[Any], shelf_code_to_id: dict[str, int]) -> None:
        with Session(self.engine) as session:
            cam = session.get(Camera, self.camera_id)
            if cam is None:
                return
            for s in sightings:
                carton = session.exec(select(Carton).where(Carton.label_code == s.carton_code)).first()
                if carton is None:
                    continue
                shelf_id = shelf_code_to_id.get(s.shelf_code) if s.shelf_code else None
                x1, y1, x2, y2 = s.bbox
                record_sighting(
                    session=session,
                    carton=carton,
                    camera=cam,
                    source="pov" if cam.kind == "pov" else "cctv",
                    level=s.level,
                    shelf_id=shelf_id,
                    seen_at=utcnow(),
                    snapshot_path=s.snapshot_path,
                    bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    track_id=s.track_id,
                    is_resting=s.is_resting,
                )


def start_camera_workers(configs: list[dict[str, Any]], engine: Any) -> dict[str, CameraWorker]:
    """Start enabled camera workers and return live handles keyed by camera_id."""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("ABT_DISABLE_WORKERS") == "1":
        return {}

    from app.main import get_settings

    settings = get_settings()
    vision_cfg = settings.get("vision", {})
    rules_cfg = settings.get("rules", {})

    workers: dict[str, CameraWorker] = {}
    for cfg in configs:
        if not cfg.get("enabled", True):
            continue
        cam_id = cfg["id"]
        # Use fast full-frame WeChat QR mode by default on CPU so 3+ cameras hit >= 5 FPS;
        # set ABT_USE_YOLO=1 to enable YOLO-World + ByteTrack on workers.
        detector_mode = (
            str(vision_cfg.get("detector", "yolo_world"))
            if os.environ.get("ABT_USE_YOLO") == "1"
            else "none"
        )
        imgsz = int(vision_cfg.get("yolo_imgsz", 640))
        if cam_id != "CAM-AISLE-2" and imgsz > 640:
            imgsz = 640
        pkwargs = {
            "detector_mode": detector_mode,
            "imgsz": imgsz,
            "conf": float(vision_cfg.get("yolo_conf", 0.15)),
            "rest_seconds": float(rules_cfg.get("rest_seconds", 3)),
            "sighting_dedup_seconds": float(vision_cfg.get("sighting_dedup_seconds", 10)),
            "track_bind_ttl": float(vision_cfg.get("track_bind_ttl", 10)),
        }
        worker = CameraWorker(cfg, engine, pipeline_kwargs=pkwargs)
        if worker.source.status == "no_signal":
            log.info("Camera %s has no signal (%s); skipping worker", cam_id, cfg.get("source"))
            continue
        worker.start()
        workers[cam_id] = worker
    return workers


def switch_camera_source(
    camera_id: str,
    source_spec: str,
    engine: Any,
    workers: dict[str, Any],
) -> str:
    """Stop any existing worker for camera_id and start a new one on source_spec."""
    old = workers.pop(camera_id, None)
    if old is not None and hasattr(old, "stop"):
        old.stop()

    from app.main import get_settings

    settings = get_settings()
    vision_cfg = settings.get("vision", {})
    rules_cfg = settings.get("rules", {})
    detector_mode = (
        str(vision_cfg.get("detector", "yolo_world"))
        if os.environ.get("ABT_USE_YOLO") == "1"
        else "none"
    )
    source_type = "push" if source_spec == "push" else "webcam" if source_spec.startswith("webcam:") else "file"
    cfg = {
        "id": camera_id,
        "source_type": source_type,
        "source": source_spec,
        "loop": True,
        "fps_process": 8 if source_type == "webcam" else 5,
    }
    worker = CameraWorker(
        cfg,
        engine,
        pipeline_kwargs={
            "detector_mode": detector_mode,
            "imgsz": 640,
            "rest_seconds": float(rules_cfg.get("rest_seconds", 3)),
        },
    )
    if worker.source.status == "no_signal":
        return "no_signal"
    worker.start()
    workers[camera_id] = worker
    return "live"
