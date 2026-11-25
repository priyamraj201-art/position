"""Offline video harness: video -> annotated MP4 + events.jsonl + read-rate & FPS summary."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.vision.pipeline import CameraContext, SightingEvent, VisionPipeline

DEFAULT_CARTON_DESTS = {
    "KYC1:BV2401": {"dest_level": 2, "dest_shelf": "L2-B2", "item_name": "2in ball valve", "po": "PO-1077"},
    "KYC1:BV2402": {"dest_level": 2, "dest_shelf": "L2-B2", "item_name": "2in ball valve", "po": "PO-1077"},
    "KYC1:BF1201": {"dest_level": 2, "dest_shelf": "L2-B1", "item_name": "3in butterfly valve", "po": "PO-1077"},
    "KYC1:YS0601": {"dest_level": 2, "dest_shelf": "L2-B1", "item_name": "Y strainer", "po": "PO-1077"},
    "KYC1:DM0401": {"dest_level": 2, "dest_shelf": "L2-B2", "item_name": "AHU-3 damper kit", "po": "PO-1077"},
    "KYC1:DM0402": {"dest_level": 2, "dest_shelf": "L2-B3", "item_name": "AHU-3 damper kit", "po": "PO-1077"},
    "KYC1:CH0201": {"dest_level": 3, "dest_shelf": "L3-A1", "item_name": "Chiller parts kit CH-2", "po": "PO-1042"},
    "KYC1:CH0202": {"dest_level": 3, "dest_shelf": "L3-A1", "item_name": "Chiller parts kit CH-2", "po": "PO-1042"},
}

DEFAULT_CAMERAS = {
    "CAM-GATE": CameraContext(id="CAM-GATE", name="Gate Cam", kind="gate", level=0),
    "CAM-HOIST-3": CameraContext(id="CAM-HOIST-3", name="Hoist Floor 3", kind="hoist", level=3),
    "CAM-AISLE-2": CameraContext(id="CAM-AISLE-2", name="Aisle Floor 2", kind="aisle", level=2),
    "CAM-POV": CameraContext(id="CAM-POV", name="POV Mobile", kind="pov", level=None),
}


def _evaluate_sighting_rules(
    sighting: SightingEvent,
    camera: CameraContext,
    carton_dests: dict[str, dict],
    open_alerts: set[tuple[str, str]],
) -> list[dict]:
    """Evaluate wrong_floor, wrong_shelf, and auto-resolve rules on a sighting."""
    events: list[dict] = []
    dest = carton_dests.get(sighting.carton_code)
    if not dest:
        return events

    dest_level = dest["dest_level"]
    dest_shelf = dest["dest_shelf"]
    code = sighting.carton_code

    if camera.kind in {"hoist", "floor_entrance", "aisle"} and camera.level is not None and camera.level != dest_level:
        key = (code, "wrong_floor")
        if key not in open_alerts:
            open_alerts.add(key)
            events.append(
                {
                    "event": "alert",
                    "type": "wrong_floor",
                    "carton_code": code,
                    "message": f"Box {code} is on Floor {camera.level} — belongs on Floor {dest_level}, shelf {dest_shelf}.",
                    "ts": sighting.seen_at,
                }
            )

    if camera.kind == "aisle" and sighting.is_resting and sighting.shelf_code is not None:
        if sighting.shelf_code != dest_shelf:
            key = (code, "wrong_shelf")
            if key not in open_alerts:
                open_alerts.add(key)
                events.append(
                    {
                        "event": "alert",
                        "type": "wrong_shelf",
                        "carton_code": code,
                        "message": f"Box {code} is on {sighting.shelf_code} — should be on {dest_shelf}.",
                        "ts": sighting.seen_at,
                    }
                )
        else:
            resolved_types = [t for (c, t) in list(open_alerts) if c == code and t in {"wrong_floor", "wrong_shelf"}]
            for t in resolved_types:
                open_alerts.discard((code, t))
                events.append(
                    {
                        "event": "alert_resolved",
                        "type": t,
                        "carton_code": code,
                        "note": "auto-resolved",
                        "status": "stored",
                        "ts": sighting.seen_at,
                    }
                )
    return events


def run_video(
    video_path: Path,
    camera_id: str,
    out_dir: Path = Path("output"),
    detector_mode: str = "yolo_world",
    imgsz: int = 960,
    fps_process: int = 8,
    rest_seconds: float = 3.0,
) -> dict:
    """Process a video file end-to-end and return summary metrics + events."""
    camera = DEFAULT_CAMERAS.get(camera_id, CameraContext(id=camera_id, name=camera_id, kind="gate", level=0))
    pipeline = VisionPipeline(
        carton_destinations=DEFAULT_CARTON_DESTS,
        detector_mode=detector_mode,
        imgsz=imgsz,
        rest_seconds=rest_seconds,
        sighting_dedup_seconds=10.0,
    )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, round(src_fps / max(fps_process, 1)))

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    out_mp4 = out_dir / f"{stem}_annotated.mp4"
    out_jsonl = out_dir / f"{stem}_events.jsonl"
    writer = cv2.VideoWriter(str(out_mp4), cv2.VideoWriter_fourcc(*"mp4v"), src_fps / step, (width, height))

    events: list[dict] = []
    open_alerts: set[tuple[str, str]] = set()
    unique_codes: set[str] = set()
    frames_with_box = 0
    frames_with_code = 0
    processed = 0
    frame_num = 0
    t0 = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_num % step == 0:
            sim_ts = frame_num / src_fps
            res = pipeline.process_frame(frame, camera, now=sim_ts, save_snapshots=False)
            processed += 1
            if res.boxes_visible > 0:
                frames_with_box += 1
            if res.boxes_with_code > 0:
                frames_with_code += 1
            unique_codes.update(res.decoded_codes)

            for s in res.sightings:
                events.append(
                    {
                        "event": "sighting",
                        "carton_code": s.carton_code,
                        "camera_id": s.camera_id,
                        "level": s.level,
                        "shelf_code": s.shelf_code,
                        "is_resting": s.is_resting,
                        "ts": s.seen_at,
                    }
                )
                events.extend(_evaluate_sighting_rules(s, camera, DEFAULT_CARTON_DESTS, open_alerts))
            writer.write(res.annotated_frame)
        frame_num += 1

    cap.release()
    writer.release()

    # For gate POV proof-of-delivery simulation, check DEL-2211 completeness
    if camera.kind == "pov":
        expected_del_2211 = {k for k, v in DEFAULT_CARTON_DESTS.items() if v["po"] == "PO-1077"}
        missing = sorted(expected_del_2211 - unique_codes)
        if missing:
            events.append(
                {
                    "event": "alert",
                    "type": "short_delivery",
                    "delivery_id": "DEL-2211",
                    "missing": missing,
                    "message": f"DEL-2211 short: expected {len(expected_del_2211)}, seen {len(unique_codes & expected_del_2211)}, missing {', '.join(missing)}",
                }
            )

    with out_jsonl.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")

    total_time = max(time.perf_counter() - t0, 1e-4)
    avg_fps = processed / total_time
    read_rate = (frames_with_code / frames_with_box) if frames_with_box else 0.0

    summary = {
        "video": str(video_path),
        "camera_id": camera_id,
        "processed_frames": processed,
        "avg_fps": round(avg_fps, 2),
        "read_rate": round(read_rate, 3),
        "cartons_read": sorted(unique_codes),
        "alerts": [e for e in events if e["event"] in {"alert", "alert_resolved"}],
        "output_mp4": str(out_mp4),
        "output_jsonl": str(out_jsonl),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VisionPipeline offline on a video file")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--camera", type=str, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument("--detector", type=str, default="yolo_world")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--fps-process", type=int, default=8)
    args = parser.parse_args()

    summary = run_video(
        args.video,
        args.camera,
        out_dir=args.out_dir,
        detector_mode=args.detector,
        imgsz=args.imgsz,
        fps_process=args.fps_process,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
