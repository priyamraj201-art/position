"""Frame annotation: carton boxes, destinations, ArUco markers, and camera HUD."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from .markers import DetectedMarker

COLOR_GREEN = (60, 220, 80)
COLOR_RED = (60, 60, 240)
COLOR_GREY = (180, 180, 180)
COLOR_CYAN = (230, 200, 60)


def annotate_frame(
    frame: np.ndarray,
    carton_overlays: Sequence[dict],
    markers: Sequence[DetectedMarker],
    camera_name: str,
    camera_level: int | None,
    fps: float,
) -> np.ndarray:
    """Draw bounding boxes, carton codes, destinations, ArUco IDs, and HUD."""
    out = frame.copy()

    for m in markers:
        pts = m.corners.astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [pts], True, COLOR_CYAN, 2)
        cv2.putText(
            out,
            f"M:{m.marker_id}",
            (int(m.center_x - 20), int(m.center_y - m.side_px * 0.6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            COLOR_CYAN,
            2,
            cv2.LINE_AA,
        )

    for item in carton_overlays:
        x1, y1, x2, y2 = [int(v) for v in item["bbox"]]
        status = item.get("visual_status", "unknown")
        color = COLOR_GREEN if status == "ok" else COLOR_RED if status == "wrong" else COLOR_GREY

        cv2.rectangle(out, (x1, y1), (x2, y2), color, 3)

        code = item.get("label_code")
        dest_shelf = item.get("dest_shelf")
        if code:
            short_code = code.replace("KYC1:", "")
            label = f"{short_code} -> {dest_shelf}" if dest_shelf else short_code
        else:
            label = f"box #{item.get('track_id', '?')}"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        ty = max(th + 8, y1)
        cv2.rectangle(out, (x1, ty - th - 8), (x1 + tw + 10, ty), color, -1)
        cv2.putText(
            out,
            label,
            (x1 + 5, ty - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (15, 15, 15),
            2,
            cv2.LINE_AA,
        )

    level_str = f"Floor {camera_level}" if camera_level is not None else "POV"
    hud = f"{camera_name} | {level_str} | {fps:.1f} FPS"
    cv2.rectangle(out, (10, 10), (14 + len(hud) * 11, 44), (15, 20, 30), -1)
    cv2.putText(out, hud, (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 248, 255), 2, cv2.LINE_AA)
    return out
