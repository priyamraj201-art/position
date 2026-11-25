"""Open-vocabulary object detector + ByteTrack wrapper (YOLO-World / YOLOE / none)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger("vision.detector")

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CLASSES = ["cardboard box", "person"]


@dataclass(frozen=True)
class Detection:
    track_id: int
    cls_name: str
    bbox_xyxy: tuple[int, int, int, int]
    conf: float


class BoxDetector:
    """Wraps Ultralytics YOLO-World + ByteTrack with fallback to detector='none'."""

    def __init__(
        self,
        detector_mode: str = "yolo_world",
        model_path: str | Path | None = None,
        imgsz: int = 960,
        conf: float = 0.15,
    ) -> None:
        self.mode = detector_mode
        self.imgsz = imgsz
        self.conf = conf
        self._model = None

        if self.mode == "none":
            logger.info("BoxDetector running in 'none' mode (full-frame QR only)")
            return

        try:
            from ultralytics import YOLO

            default_model = PACKAGE_ROOT / "models" / "yolov8s-worldv2.pt"
            target = str(model_path or default_model)
            if self.mode == "yoloe" or not Path(target).exists():
                alt = PACKAGE_ROOT / "models" / "yoloe-11s-seg.pt"
                if self.mode == "yoloe" and alt.exists():
                    target = str(alt)
                elif not Path(target).exists():
                    target = "yolov8s-worldv2.pt" if self.mode == "yolo_world" else "yoloe-11s-seg.pt"

            model = YOLO(target)
            if hasattr(model, "set_classes"):
                model.set_classes(CLASSES)
            self._model = model
            logger.info("Loaded detector %s (imgsz=%d, conf=%.2f)", target, imgsz, conf)
        except (ImportError, OSError, RuntimeError) as exc:
            logger.warning("Failed to load YOLO detector (%s); falling back to mode='none'", exc)
            self.mode = "none"
            self._model = None

    def track(self, frame: np.ndarray) -> list[Detection]:
        """Run detection + ByteTrack on a single BGR frame."""
        if self._model is None or self.mode == "none":
            return []

        results = self._model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            imgsz=self.imgsz,
            conf=self.conf,
            verbose=False,
        )
        if not results:
            return []

        res = results[0]
        boxes = res.boxes
        if boxes is None or len(boxes) == 0:
            return []

        names = res.names or {0: "cardboard box", 1: "person"}
        detections: list[Detection] = []
        xyxy_arr = boxes.xyxy.cpu().numpy()
        cls_arr = boxes.cls.cpu().numpy()
        conf_arr = boxes.conf.cpu().numpy()
        id_arr = boxes.id.cpu().numpy() if boxes.id is not None else None

        for idx in range(len(xyxy_arr)):
            x1, y1, x2, y2 = [int(v) for v in xyxy_arr[idx]]
            cls_idx = int(cls_arr[idx])
            cls_name = str(names.get(cls_idx, "cardboard box"))
            track_id = int(id_arr[idx]) if id_arr is not None else -(idx + 1)
            detections.append(
                Detection(
                    track_id=track_id,
                    cls_name=cls_name,
                    bbox_xyxy=(x1, y1, x2, y2),
                    conf=float(conf_arr[idx]),
                )
            )
        return detections
