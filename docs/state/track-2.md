# Track 2 State — Computer Vision, Labels & Offline Harness

- **Owner**: Priyam (`@priyamraj201-art`) + Agent 2
- **Branch**: `feat/track-2-vision-labels`
- **Status**: READY_FOR_HANDOFF
- **Current Task**: Wave 2 complete — ready for Track 1 `worker.py` wiring (`[HANDOFF]`)
- **Last Completed**: Implemented full Track 2 vision pipeline, PDF labels, synthetic videos, and offline harness; all 6 Track 2 tests pass. Verified both `detector=none` (**13.79–28.45 FPS** CPU, `read_rate: 1.0`) and `yolo_world` (`yolov8s-worldv2.pt`, `imgsz=640`, WeChat QR weights: **4.43 FPS** CPU, `read_rate: 1.0`).
- **Blockers**: None
- **Next Sync**: Post `[TRACK-2 -> TRACK-1] [HANDOFF]` on GitHub Issue #1 once branch is pushed.

### Checklist
- [x] `scripts/make_labels.py` (4×6 + A4 carton PDFs + ArUco marker PDF) + `tests/test_labels.py`
- [x] `app/vision/detector.py` (YOLO-World `yolov8s-worldv2.pt` + ByteTrack + fallbacks)
- [x] `app/vision/qr.py` (WeChat QR + 15% pad + 2× upscale + full-frame sweep)
- [x] `app/vision/markers.py` (ArUco `DICT_4X4_50` + shelf association)
- [x] `app/vision/privacy.py` (top 35% person head blur) & `annotate.py`
- [x] `app/vision/pipeline.py` & `sources.py`
- [x] `scripts/make_synthetic_video.py` & `scripts/run_on_video.py` (verified all 3 scenarios + 13.79 FPS CPU)
