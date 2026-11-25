"""Core 8-step VisionPipeline: detection, QR binding, ArUco shelf association, motion, and annotation."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .annotate import annotate_frame
from .detector import BoxDetector
from .markers import DetectedMarker, MarkerDetector, associate_box_to_shelf
from .privacy import blur_person_heads
from .qr import QRDecoder


@dataclass
class CameraContext:
    id: str
    name: str
    kind: str  # gate | hoist | floor_entrance | aisle | pov
    level: int | None = None
    facility_id: str | None = None


@dataclass
class SightingEvent:
    carton_code: str
    camera_id: str
    level: int | None
    shelf_code: str | None
    is_resting: bool
    seen_at: float
    bbox: tuple[int, int, int, int]
    track_id: int
    snapshot_path: str | None = None


@dataclass
class FrameResult:
    annotated_frame: np.ndarray
    sightings: list[SightingEvent]
    decoded_codes: list[str]
    boxes_visible: int
    boxes_with_code: int
    fps: float


@dataclass
class _TrackBinding:
    code: str
    last_seen: float


@dataclass
class _MotionHistory:
    samples: deque[tuple[float, float, float]] = field(default_factory=deque)  # (ts, cx, cy)


class VisionPipeline:
    """Stateful per-camera vision pipeline implementing PRD-03 §3.1."""

    def __init__(
        self,
        marker_to_shelf: dict[int, str] | None = None,
        carton_destinations: dict[str, dict[str, Any]] | None = None,
        detector_mode: str = "yolo_world",
        imgsz: int = 960,
        conf: float = 0.15,
        rest_seconds: float = 3.0,
        sighting_dedup_seconds: float = 10.0,
        track_bind_ttl: float = 10.0,
        snapshot_dir: str | Path | None = None,
        wechat_dir: str | Path | None = None,
    ) -> None:
        pkg_root = Path(__file__).resolve().parents[2]
        self.marker_to_shelf = marker_to_shelf or {
            1: "L2-B1",
            2: "L2-B2",
            3: "L2-B3",
            11: "L3-A1",
            12: "L3-A2",
        }
        self.carton_destinations = carton_destinations or {}
        self.rest_seconds = rest_seconds
        self.sighting_dedup_seconds = sighting_dedup_seconds
        self.track_bind_ttl = track_bind_ttl
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else (pkg_root / "data" / "snapshots")
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        self.detector = BoxDetector(detector_mode=detector_mode, imgsz=imgsz, conf=conf)
        self.qr_decoder = QRDecoder(wechat_dir=wechat_dir or (pkg_root / "models" / "wechat"))
        self.marker_detector = MarkerDetector()

        self._frame_idx = 0
        self._track_cache: dict[int, _TrackBinding] = {}
        self._motion: dict[str, _MotionHistory] = {}
        self._last_sighting: dict[tuple[str, str], tuple[float, str | None, bool]] = {}
        self._last_ts: float = time.perf_counter()
        self._ema_fps: float = 0.0

    def _prune_track_cache(self, now: float) -> None:
        expired = [tid for tid, b in self._track_cache.items() if now - b.last_seen > self.track_bind_ttl]
        for tid in expired:
            del self._track_cache[tid]

    def _update_resting(self, code: str, bbox: tuple[int, int, int, int], frame_w: int, now: float) -> bool:
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        hist = self._motion.setdefault(code, _MotionHistory())
        hist.samples.append((now, cx, cy))

        while hist.samples and now - hist.samples[0][0] > self.rest_seconds:
            if len(hist.samples) <= 2:
                break
            hist.samples.popleft()

        if len(hist.samples) < 2 or (now - hist.samples[0][0]) < self.rest_seconds * 0.8:
            return False

        xs = [s[1] for s in hist.samples]
        ys = [s[2] for s in hist.samples]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        return span < 0.04 * frame_w

    def _visual_status(
        self,
        code: str | None,
        camera: CameraContext,
        shelf_code: str | None,
        is_resting: bool,
    ) -> str:
        if not code or code not in self.carton_destinations:
            return "unknown"
        dest = self.carton_destinations[code]
        dest_level = dest.get("dest_level")
        dest_shelf = dest.get("dest_shelf")
        if (
            camera.kind in {"hoist", "floor_entrance", "aisle"}
            and camera.level is not None
            and dest_level is not None
            and camera.level != dest_level
        ):
            return "wrong"
        if camera.kind == "aisle" and is_resting and shelf_code is not None:
            if dest_shelf and shelf_code != dest_shelf:
                return "wrong"
            if dest_shelf and shelf_code == dest_shelf:
                return "ok"
        return "ok"

    def process_frame(
        self,
        frame: np.ndarray,
        camera: CameraContext,
        now: float | None = None,
        save_snapshots: bool = True,
    ) -> FrameResult:
        """Run the 8-step vision pipeline on a single BGR frame."""
        t_start = time.perf_counter()
        ts = now if now is not None else time.time()
        self._frame_idx += 1
        self._prune_track_cache(ts)

        h, w = frame.shape[:2]

        # Step 1: YOLO-World + ByteTrack
        detections = self.detector.track(frame)
        box_dets = [d for d in detections if d.cls_name != "person"]
        person_boxes = [d.bbox_xyxy for d in detections if d.cls_name == "person"]

        # Step 2: Bind box track_ids to QR codes
        box_codes: list[str | None] = []
        for d in box_dets:
            code: str | None = None
            if d.track_id >= 0 and d.track_id in self._track_cache:
                binding = self._track_cache[d.track_id]
                binding.last_seen = ts
                code = binding.code
            else:
                code = self.qr_decoder.decode_crop(frame, d.bbox_xyxy)
                if code and d.track_id >= 0:
                    self._track_cache[d.track_id] = _TrackBinding(code=code, last_seen=ts)
            box_codes.append(code)

        # Step 3: Full-frame QR sweep every 4th frame (or always when detector == 'none')
        full_sweep = self.detector.mode == "none" or (self._frame_idx % 4 == 0)
        pseudo_boxes: list[tuple[int, tuple[int, int, int, int], str]] = []
        if full_sweep:
            for qr in self.qr_decoder.decode_full_frame(frame):
                matched = False
                for idx, d in enumerate(box_dets):
                    x1, y1, x2, y2 = d.bbox_xyxy
                    if x1 <= qr.center_x <= x2 and y1 <= qr.center_y <= y2:
                        if box_codes[idx] is None:
                            box_codes[idx] = qr.code
                            if d.track_id >= 0:
                                self._track_cache[d.track_id] = _TrackBinding(code=qr.code, last_seen=ts)
                        matched = True
                        break
                if not matched and len(qr.polygon) > 0:
                    px1 = max(0, int(qr.polygon[:, 0].min()) - 20)
                    py1 = max(0, int(qr.polygon[:, 1].min()) - 20)
                    px2 = min(w, int(qr.polygon[:, 0].max()) + 20)
                    py2 = min(h, int(qr.polygon[:, 1].max()) + 20)
                    pseudo_boxes.append((-1, (px1, py1, px2, py2), qr.code))

        # Combine tracked boxes and any pseudo-boxes from full-frame QR
        combined: list[tuple[int, tuple[int, int, int, int], str | None]] = [
            (d.track_id, d.bbox_xyxy, code)
            for d, code in zip(box_dets, box_codes, strict=True)
        ] + pseudo_boxes

        # Step 4: ArUco marker detection
        markers: list[DetectedMarker] = self.marker_detector.detect(frame)

        # Steps 5-7: Shelf association, motion state, sighting emission & snapshots
        sightings: list[SightingEvent] = []
        overlays: list[dict[str, Any]] = []
        decoded_codes: list[str] = []
        boxes_with_code = 0

        for tid, bbox, code in combined:
            shelf_code: str | None = None
            is_resting = False
            if code:
                boxes_with_code += 1
                decoded_codes.append(code)
                if camera.kind == "aisle":
                    shelf_code = associate_box_to_shelf(bbox, markers, self.marker_to_shelf)
                is_resting = self._update_resting(code, bbox, w, ts)

                key = (camera.id, code)
                prev = self._last_sighting.get(key)
                should_emit = (
                    prev is None
                    or prev[1] != shelf_code
                    or (not prev[2] and is_resting)
                    or (ts - prev[0]) >= self.sighting_dedup_seconds
                )
                if should_emit:
                    snap_path: str | None = None
                    if save_snapshots:
                        blurred = blur_person_heads(frame, person_boxes)
                        short = code.replace("KYC1:", "")
                        snap_name = f"{camera.id}_{short}_{int(ts * 1000)}.jpg"
                        full_snap = self.snapshot_dir / snap_name
                        cv2.imwrite(str(full_snap), blurred)
                        snap_path = f"data/snapshots/{snap_name}"

                    self._last_sighting[key] = (ts, shelf_code, is_resting)
                    sightings.append(
                        SightingEvent(
                            carton_code=code,
                            camera_id=camera.id,
                            level=camera.level,
                            shelf_code=shelf_code,
                            is_resting=is_resting,
                            seen_at=ts,
                            bbox=bbox,
                            track_id=tid,
                            snapshot_path=snap_path,
                        )
                    )

            dest_info = self.carton_destinations.get(code or "", {})
            overlays.append(
                {
                    "track_id": tid,
                    "bbox": bbox,
                    "label_code": code,
                    "dest_shelf": dest_info.get("dest_shelf"),
                    "visual_status": self._visual_status(code, camera, shelf_code, is_resting),
                }
            )

        elapsed = max(time.perf_counter() - t_start, 1e-4)
        inst_fps = 1.0 / elapsed
        self._ema_fps = inst_fps if self._ema_fps == 0.0 else (0.8 * self._ema_fps + 0.2 * inst_fps)

        # Step 8: Annotate frame
        annotated = annotate_frame(
            frame=frame,
            carton_overlays=overlays,
            markers=markers,
            camera_name=camera.name,
            camera_level=camera.level,
            fps=self._ema_fps,
        )

        return FrameResult(
            annotated_frame=annotated,
            sightings=sightings,
            decoded_codes=decoded_codes,
            boxes_visible=len(combined),
            boxes_with_code=boxes_with_code,
            fps=self._ema_fps,
        )
