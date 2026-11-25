"""Privacy protection: blur the top 35% (head/face region) of every person box."""

from __future__ import annotations

import cv2
import numpy as np


def blur_person_heads(
    frame: np.ndarray,
    person_boxes: list[tuple[int, int, int, int]],
) -> np.ndarray:
    """Return a copy of frame with the top 35% of every person bbox blurred."""
    if not person_boxes:
        return frame

    out = frame.copy()
    h, w = out.shape[:2]
    for x1, y1, x2, y2 in person_boxes:
        cx1 = max(0, int(x1))
        cy1 = max(0, int(y1))
        cx2 = min(w, int(x2))
        cy2 = min(h, int(y1 + 0.35 * (y2 - y1)))
        if cx2 <= cx1 or cy2 <= cy1:
            continue
        roi = out[cy1:cy2, cx1:cx2]
        ksize = max(15, ((min(roi.shape[0], roi.shape[1]) // 3) | 1))
        out[cy1:cy2, cx1:cx2] = cv2.GaussianBlur(roi, (ksize, ksize), 0)
    return out
