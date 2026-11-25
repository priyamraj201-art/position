"""Generate the 3 synthetic scenario videos for offline/CI verification before real filming."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.make_labels import make_aruco_pil, make_qr_pil

WIDTH, HEIGHT = 1280, 720
FPS = 15


def _paste_cardboard_box(
    frame: np.ndarray,
    qr_code: str,
    x: int,
    y: int,
    w: int = 240,
    h: int = 240,
) -> None:
    """Draw a cardboard-colored box with a crisp white QR label pasted on its face."""
    cv2.rectangle(frame, (x, y), (x + w, y + h), (95, 135, 175), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (55, 85, 120), 3)

    qr_pil = make_qr_pil(qr_code, box_size=8, border=2)
    qr_np = cv2.cvtColor(np.array(qr_pil), cv2.COLOR_RGB2BGR)
    label_size = min(w, h) - 36
    qr_resized = cv2.resize(qr_np, (label_size, label_size), interpolation=cv2.INTER_AREA)

    lx = x + (w - label_size) // 2
    ly = y + (h - label_size) // 2
    cv2.rectangle(frame, (lx - 8, ly - 8), (lx + label_size + 8, ly + label_size + 8), (255, 255, 255), -1)
    frame[ly : ly + label_size, lx : lx + label_size] = qr_resized


def _paste_aruco(frame: np.ndarray, marker_id: int, cx: int, cy: int, size: int = 110, title: str = "") -> None:
    pil_img = make_aruco_pil(marker_id, size_px=size)
    m_np = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    x1 = cx - size // 2
    y1 = cy - size // 2
    cv2.rectangle(frame, (x1 - 14, y1 - 14), (x1 + size + 14, y1 + size + 34), (255, 255, 255), -1)
    frame[y1 : y1 + size, x1 : x1 + size] = m_np
    if title:
        cv2.putText(frame, title, (x1 - 6, y1 + size + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 2)


def _base_bg(label: str) -> np.ndarray:
    bg = np.full((HEIGHT, WIDTH, 3), (45, 50, 58), dtype=np.uint8)
    cv2.line(bg, (0, 560), (WIDTH, 560), (80, 90, 100), 3)
    cv2.putText(bg, label, (30, HEIGHT - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (170, 180, 195), 2)
    return bg


def make_video_01_gate_pov(out_path: Path) -> None:
    """Scenario 1: 5 of 6 DEL-2211 cartons visible (DM0402 omitted)."""
    codes = ["KYC1:BV2401", "KYC1:BV2402", "KYC1:BF1201", "KYC1:YS0601", "KYC1:DM0401"]
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    for code in codes:
        for f in range(FPS * 2):
            frame = _base_bg("SYNTHETIC 01 - GATE POV (DEL-2211)")
            offset_x = int(520 + np.sin(f * 0.15) * 20)
            _paste_cardboard_box(frame, code, offset_x, 220, 260, 260)
            writer.write(frame)
    writer.release()


def make_video_02_wrong_floor(out_path: Path) -> None:
    """Scenario 2: BV2401 (dest Floor 2) + CH0201 (dest Floor 3) carried past Floor 3 Hoist."""
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    # Pass 1: BV2401
    for i in range(FPS * 3):
        frame = _base_bg("SYNTHETIC 02 - FLOOR 3 HOIST")
        x = int(120 + (i / (FPS * 3)) * 820)
        _paste_cardboard_box(frame, "KYC1:BV2401", x, 240, 240, 240)
        writer.write(frame)
    # Blank gap
    for _ in range(FPS):
        writer.write(_base_bg("SYNTHETIC 02 - FLOOR 3 HOIST"))
    # Pass 2: CH0201
    for i in range(FPS * 3):
        frame = _base_bg("SYNTHETIC 02 - FLOOR 3 HOIST")
        x = int(120 + (i / (FPS * 3)) * 820)
        _paste_cardboard_box(frame, "KYC1:CH0201", x, 240, 240, 240)
        writer.write(frame)
    writer.release()


def make_video_03_shelf(out_path: Path) -> None:
    """Scenario 3: DM0401 rests on L2-B3 (marker 3) for 4s, then moves to L2-B2 (marker 2) for 4s."""
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))

    def draw_shelves(frame: np.ndarray) -> None:
        _paste_aruco(frame, 1, 240, 500, 100, "L2-B1")
        _paste_aruco(frame, 2, 640, 500, 100, "L2-B2")
        _paste_aruco(frame, 3, 1040, 500, 100, "L2-B3")

    # Rest on L2-B3 (marker 3 at x=1040) for 4s
    for _ in range(FPS * 4):
        frame = _base_bg("SYNTHETIC 03 - FLOOR 2 AISLE")
        draw_shelves(frame)
        _paste_cardboard_box(frame, "KYC1:DM0401", 920, 190, 230, 230)
        writer.write(frame)

    # Slide from L2-B3 to L2-B2 over 1s
    for i in range(FPS):
        frame = _base_bg("SYNTHETIC 03 - FLOOR 2 AISLE")
        draw_shelves(frame)
        x = int(920 - (i / FPS) * 400)
        _paste_cardboard_box(frame, "KYC1:DM0401", x, 190, 230, 230)
        writer.write(frame)

    # Rest on L2-B2 (marker 2 at x=640) for 4s
    for _ in range(FPS * 4):
        frame = _base_bg("SYNTHETIC 03 - FLOOR 2 AISLE")
        draw_shelves(frame)
        _paste_cardboard_box(frame, "KYC1:DM0401", 520, 190, 230, 230)
        writer.write(frame)

    writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic demo videos")
    parser.add_argument("--out-dir", type=Path, default=Path("videos"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    make_video_01_gate_pov(args.out_dir / "01_gate_pov.mp4")
    make_video_02_wrong_floor(args.out_dir / "02_wrong_floor.mp4")
    make_video_03_shelf(args.out_dir / "03_shelf.mp4")
    print(f"Generated 3 synthetic videos in {args.out_dir}")


if __name__ == "__main__":
    main()
