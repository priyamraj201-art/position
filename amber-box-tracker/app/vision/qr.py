"""WeChat QR decoder with crop padding/upscaling and ArUco/standard QR fallbacks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("vision.qr")

KYC1_PATTERN = re.compile(r"^KYC1:[A-Z0-9]{6}$")


@dataclass(frozen=True)
class DecodedQR:
    code: str
    center_x: float
    center_y: float
    polygon: np.ndarray  # shape (4, 2)


class QRDecoder:
    """CNN-based WeChatQRCode decoder with automatic fallbacks."""

    def __init__(self, wechat_dir: Path | str = "models/wechat") -> None:
        self._wechat = None
        self._aruco_qr = None
        self._std_qr = cv2.QRCodeDetector()

        wdir = Path(wechat_dir)
        files = [
            wdir / "detect.prototxt",
            wdir / "detect.caffemodel",
            wdir / "sr.prototxt",
            wdir / "sr.caffemodel",
        ]
        try:
            if all(f.exists() for f in files):
                self._wechat = cv2.wechat_qrcode_WeChatQRCode(
                    str(files[0]), str(files[1]), str(files[2]), str(files[3])
                )
                logger.info("Loaded WeChatQRCode with super-resolution weights from %s", wdir)
            else:
                self._wechat = cv2.wechat_qrcode_WeChatQRCode()
                logger.info("Loaded WeChatQRCode with built-in default model (weights not found)")
        except (cv2.error, AttributeError, RuntimeError) as exc:
            logger.warning("WeChatQRCode unavailable (%s); using QRCodeDetectorAruco fallback", exc)
            try:
                self._aruco_qr = cv2.QRCodeDetectorAruco()
            except (cv2.error, AttributeError):
                self._aruco_qr = None

    def _raw_decode(self, img: np.ndarray) -> list[tuple[str, np.ndarray]]:
        results: list[tuple[str, np.ndarray]] = []
        if self._wechat is not None:
            texts, points = self._wechat.detectAndDecode(img)
            for text, pts in zip(texts or [], points or [], strict=False):
                cleaned = (text or "").strip().upper()
                if KYC1_PATTERN.match(cleaned):
                    results.append((cleaned, np.asarray(pts, dtype=np.float32).reshape(-1, 2)))
            if results:
                return results

        if self._aruco_qr is not None:
            ok, texts, points, _ = self._aruco_qr.detectAndDecodeMulti(img)
            if ok and texts is not None and points is not None:
                for text, pts in zip(texts, points, strict=False):
                    cleaned = (text or "").strip().upper()
                    if KYC1_PATTERN.match(cleaned):
                        results.append((cleaned, np.asarray(pts, dtype=np.float32).reshape(-1, 2)))
                if results:
                    return results

        ok, texts, points, _ = self._std_qr.detectAndDecodeMulti(img)
        if ok and texts is not None and points is not None:
            for text, pts in zip(texts, points, strict=False):
                cleaned = (text or "").strip().upper()
                if KYC1_PATTERN.match(cleaned):
                    results.append((cleaned, np.asarray(pts, dtype=np.float32).reshape(-1, 2)))
        return results

    def decode_full_frame(self, frame: np.ndarray) -> list[DecodedQR]:
        """Decode all valid KYC1 QR codes across the full frame."""
        decoded: list[DecodedQR] = []
        for code, pts in self._raw_decode(frame):
            cx = float(pts[:, 0].mean()) if len(pts) else 0.0
            cy = float(pts[:, 1].mean()) if len(pts) else 0.0
            decoded.append(DecodedQR(code=code, center_x=cx, center_y=cy, polygon=pts))
        return decoded

    def decode_crop(
        self,
        frame: np.ndarray,
        bbox_xyxy: tuple[int, int, int, int],
        pad_ratio: float = 0.15,
        min_short_side: int = 300,
    ) -> str | None:
        """Crop bbox with 15% padding, upscale 2x if short side < 300px, and decode."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox_xyxy
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        px = int(bw * pad_ratio)
        py = int(bh * pad_ratio)

        cx1 = max(0, x1 - px)
        cy1 = max(0, y1 - py)
        cx2 = min(w, x2 + px)
        cy2 = min(h, y2 + py)
        if cx2 <= cx1 or cy2 <= cy1:
            return None

        crop = frame[cy1:cy2, cx1:cx2]
        short_side = min(crop.shape[0], crop.shape[1])
        if short_side < min_short_side:
            crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

        matches = self._raw_decode(crop)
        return matches[0][0] if matches else None
