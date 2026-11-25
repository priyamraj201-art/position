"""Tests for vision privacy, shelf association, and 3 synthetic scenario videos."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.markers import DetectedMarker, associate_box_to_shelf
from app.vision.privacy import blur_person_heads
from scripts.make_synthetic_video import (
    make_video_01_gate_pov,
    make_video_02_wrong_floor,
    make_video_03_shelf,
)
from scripts.run_on_video import run_video


def test_privacy_blurs_top_35_percent_only() -> None:
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    # Sharp checkerboard inside person bbox (40, 20, 140, 180) -> height 160, top 35% = 56px (y=20..76)
    frame[20:180, 40:140:2] = 255
    blurred = blur_person_heads(frame, [(40, 20, 140, 180)])

    # Top head region should be smoothed (variance reduced)
    assert blurred[25:70, 50:130].std() < frame[25:70, 50:130].std()
    # Bottom body region (y=90..175) must remain untouched
    assert np.array_equal(blurred[90:175, 40:140], frame[90:175, 40:140])


def test_shelf_marker_association() -> None:
    markers = [
        DetectedMarker(marker_id=1, center_x=200, center_y=400, side_px=60, corners=np.zeros((4, 2))),
        DetectedMarker(marker_id=2, center_x=500, center_y=400, side_px=60, corners=np.zeros((4, 2))),
    ]
    mapping = {1: "L2-B1", 2: "L2-B2"}
    # Box bottom y=350 (within 3*60=180 of y=400), center_x=480 -> closer to marker 2
    shelf = associate_box_to_shelf((400, 150, 560, 350), markers, mapping)
    assert shelf == "L2-B2"

    # Box too far vertically (bottom y=100, distance 300 > 180)
    assert associate_box_to_shelf((400, 10, 560, 100), markers, mapping) is None


def test_synthetic_scenarios_end_to_end(tmp_path: Path) -> None:
    v1 = tmp_path / "01_gate_pov.mp4"
    v2 = tmp_path / "02_wrong_floor.mp4"
    v3 = tmp_path / "03_shelf.mp4"
    make_video_01_gate_pov(v1)
    make_video_02_wrong_floor(v2)
    make_video_03_shelf(v3)

    # Use detector_mode='none' in unit test for fast deterministic CI;
    # YOLO-World throughput is benchmarked separately via scripts/run_on_video.py
    s1 = run_video(v1, "CAM-POV", out_dir=tmp_path / "out1", detector_mode="none", fps_process=5)
    assert any(a["type"] == "short_delivery" and "KYC1:DM0402" in a["missing"] for a in s1["alerts"])

    s2 = run_video(v2, "CAM-HOIST-3", out_dir=tmp_path / "out2", detector_mode="none", fps_process=5)
    wf_alerts = [a for a in s2["alerts"] if a["type"] == "wrong_floor"]
    assert len(wf_alerts) == 1
    assert wf_alerts[0]["carton_code"] == "KYC1:BV2401"

    s3 = run_video(v3, "CAM-AISLE-2", out_dir=tmp_path / "out3", detector_mode="none", fps_process=5, rest_seconds=2.0)
    ws_alerts = [a for a in s3["alerts"] if a["event"] == "alert" and a["type"] == "wrong_shelf"]
    resolved = [a for a in s3["alerts"] if a["event"] == "alert_resolved" and a["type"] == "wrong_shelf"]
    assert len(ws_alerts) == 1
    assert len(resolved) == 1
    assert resolved[0]["status"] == "stored"
