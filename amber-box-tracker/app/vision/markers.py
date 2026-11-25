"""ArUco DICT_4X4_50 marker detection and shelf association."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class DetectedMarker:
    marker_id: int
    center_x: float
    center_y: float
    side_px: float
    corners: np.ndarray


class MarkerDetector:
    """Wraps cv2.aruco.ArucoDetector for DICT_4X4_50 shelf markers."""

    def __init__(self) -> None:
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        params = cv2.aruco.DetectorParameters()
        self._detector = cv2.aruco.ArucoDetector(aruco_dict, params)

    def detect(self, frame: np.ndarray) -> list[DetectedMarker]:
        corners_list, ids, _ = self._detector.detectMarkers(frame)
        if ids is None:
            return []

        results: list[DetectedMarker] = []
        for corners, mid in zip(corners_list, ids.flatten(), strict=True):
            pts = corners[0]
            cx = float(pts[:, 0].mean())
            cy = float(pts[:, 1].mean())
            side = float(
                (np.linalg.norm(pts[0] - pts[1]) + np.linalg.norm(pts[1] - pts[2])) / 2.0
            )
            results.append(
                DetectedMarker(
                    marker_id=int(mid),
                    center_x=cx,
                    center_y=cy,
                    side_px=max(side, 1.0),
                    corners=pts,
                )
            )
        return results


def associate_box_to_shelf(
    box_xyxy: tuple[int, int, int, int],
    markers: list[DetectedMarker],
    marker_to_shelf: dict[int, str],
) -> str | None:
    """Associate a carton bbox with the nearest qualifying ArUco shelf marker.

    Rule (PRD-03 §3.1 step 5):
      - Filter markers whose center_y is within 3 * marker_side vertically of the box's bottom edge.
      - Pick the nearest marker horizontally to the box center_x.
    """
    if not markers:
        return None

    x1, _y1, x2, y2 = box_xyxy
    box_cx = (x1 + x2) / 2.0

    candidates = [
        m
        for m in markers
        if m.marker_id in marker_to_shelf and abs(m.center_y - y2) <= 3.0 * m.side_px
    ]
    if not candidates:
        return None

    nearest = min(candidates, key=lambda m: abs(m.center_x - box_cx))
    return marker_to_shelf[nearest.marker_id]
