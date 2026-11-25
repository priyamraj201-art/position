"""Camera frame sources: VideoFileSource, RTSPSource, WebcamSource, PushSource."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("vision.sources")


class FrameSource(ABC):
    """Abstract frame source interface for camera workers."""

    status: str = "no_signal"

    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Return next BGR frame or None when unavailable/ended."""

    @abstractmethod
    def close(self) -> None:
        """Release underlying capture resources."""


class VideoFileSource(FrameSource):
    """Plays an MP4/video file at real-time speed, looping if configured."""

    def __init__(self, path: str | Path, loop: bool = True, pace_realtime: bool = True) -> None:
        self.path = Path(path)
        self.loop = loop
        self.pace_realtime = pace_realtime
        self._cap: cv2.VideoCapture | None = None
        self._fps: float = 30.0
        self._last_frame_ts: float = 0.0
        self._open()

    def _open(self) -> None:
        if not self.path.exists():
            logger.warning("Video file not found: %s (marking camera no_signal)", self.path)
            self.status = "no_signal"
            self._cap = None
            return
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            logger.warning("Failed to open video file: %s", self.path)
            self.status = "no_signal"
            self._cap = None
            return
        self._cap = cap
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if fps and fps > 1.0 else 30.0
        self.status = "live"

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None

        if self.pace_realtime and self._last_frame_ts > 0:
            interval = 1.0 / self._fps
            elapsed = time.perf_counter() - self._last_frame_ts
            if elapsed < interval:
                time.sleep(interval - elapsed)

        ok, frame = self._cap.read()
        if not ok:
            if self.loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
            if not ok:
                return None

        self._last_frame_ts = time.perf_counter()
        self.status = "live"
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class CaptureSource(FrameSource):
    """Webcam or RTSP stream source."""

    def __init__(self, target: int | str) -> None:
        self.target = target
        self._cap = cv2.VideoCapture(target)
        self.status = "live" if self._cap.isOpened() else "no_signal"
        if self.status == "no_signal":
            logger.warning("Stream/webcam unavailable: %s", target)

    def read(self) -> np.ndarray | None:
        if not self._cap.isOpened():
            self.status = "no_signal"
            return None
        ok, frame = self._cap.read()
        if not ok:
            return None
        self.status = "live"
        return frame

    def close(self) -> None:
        self._cap.release()


class PushSource(FrameSource):
    """Thread-safe single-slot latest-frame buffer for phone/glasses WebSocket frames."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self.status = "live"

    def push_jpeg(self, jpeg_bytes: bytes) -> bool:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return False
        with self._lock:
            self._latest = frame
        return True

    def push_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest = frame

    def read(self) -> np.ndarray | None:
        with self._lock:
            frame = self._latest
            self._latest = None
            return frame

    def close(self) -> None:
        with self._lock:
            self._latest = None


def build_source(source_spec: str, loop: bool = True) -> FrameSource:
    """Factory creating the appropriate FrameSource from config/cameras.yaml source string."""
    if source_spec.startswith("file:"):
        return VideoFileSource(source_spec[len("file:") :], loop=loop)
    if source_spec.startswith("webcam:"):
        return CaptureSource(int(source_spec[len("webcam:") :]))
    if source_spec.startswith("rtsp://"):
        return CaptureSource(source_spec)
    if source_spec == "push":
        return PushSource()
    return VideoFileSource(source_spec, loop=loop)
