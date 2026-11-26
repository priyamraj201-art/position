"""One-shot setup: directories, model weights, database, seed (PRD-01 section 1.5).

    python scripts/setup.py

Every external download has an offline fallback (RULES_AND_ANTIPATTERNS 1.4):
a failed WeChat weights download is a warning, not an error - the QR decoder
falls back to cv2.wechat_qrcode_WeChatQRCode() with no args, then to
cv2.QRCodeDetectorAruco().
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from importlib import metadata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

WECHAT_BASE = (
    "https://raw.githubusercontent.com/WeChatCV/opencv_3rdparty/wechat_qrcode/"
)
WECHAT_FILES = [
    "detect.prototxt",
    "detect.caffemodel",
    "sr.prototxt",
    "sr.caffemodel",
]

DIRS = ["data", "data/snapshots", "data/proof", "models/wechat", "videos", "output"]


def enforce_opencv_rule() -> None:
    """Ultralytics depends on opencv-python, which then shadows the pinned
    opencv-contrib-python-headless build (repo rule: never both - the contrib
    build alone carries cv2.wechat_qrcode). Pip cannot exclude transitive
    deps, so remove the intruders after install and verify the contrib build.
    """
    intruders = []
    for dist in ("opencv-python", "opencv-python-headless"):
        try:
            metadata.version(dist)
        except metadata.PackageNotFoundError:
            continue
        intruders.append(dist)
    if not intruders:
        print("[setup] opencv rule OK: only the contrib headless build is installed")
        return
    # The intruder's files shadow/replace contrib's, so removing it leaves cv2
    # broken: force-reinstall the pinned contrib build afterwards.
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", *intruders], check=True
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps",
             "opencv-contrib-python-headless==4.10.0.84"], check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run(["uv", "pip", "uninstall", *intruders], check=True)
        subprocess.run(
            ["uv", "pip", "install", "--reinstall-package",
             "opencv-contrib-python-headless", "--no-deps",
             "opencv-contrib-python-headless==4.10.0.84"], check=True
        )
    import cv2

    assert hasattr(cv2, "wechat_qrcode_WeChatQRCode"), (
        "cv2.wechat_qrcode missing after cleanup - reinstall "
        "opencv-contrib-python-headless==4.10.0.84"
    )
    print("[setup] removed", ", ".join(intruders), "- contrib headless build verified")


def ensure_dirs() -> None:
    for rel in DIRS:
        (BASE_DIR / rel).mkdir(parents=True, exist_ok=True)
    print("[setup] directories ready:", ", ".join(DIRS))


def download_wechat_weights() -> None:
    dest_dir = BASE_DIR / "models" / "wechat"
    for name in WECHAT_FILES:
        dest = dest_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"[setup] wechat: {name} already present")
            continue
        url = WECHAT_BASE + name
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                dest.write_bytes(resp.read())
            print(f"[setup] wechat: downloaded {name}")
        except Exception as exc:  # noqa: BLE001 - offline fallback must never crash setup (RULES 1.4)
            print(
                f"[setup] WARNING: could not download {name} ({exc}). "
                "QR decoding will use the no-args WeChatQRCode / "
                "QRCodeDetectorAruco fallback."
            )


def init_database() -> None:
    from app.db import DB_PATH, get_engine, init_db
    from app.seed import seed_if_empty
    from sqlmodel import Session

    engine = get_engine(str(DB_PATH))
    init_db(engine)
    with Session(engine) as session:
        loaded = seed_if_empty(session)
    state = "loaded seed" if loaded else "already seeded"
    print(f"[setup] database ready at {DB_PATH} ({state})")


def print_summary() -> None:
    from app import models
    from app.db import DB_PATH, get_engine
    from sqlmodel import Session, select

    engine = get_engine(str(DB_PATH))
    with Session(engine) as session:
        counts = {
            "shelves": len(session.exec(select(models.Shelf)).all()),
            "cartons": len(session.exec(select(models.Carton)).all()),
            "deliveries": len(session.exec(select(models.Delivery)).all()),
            "cameras": len(session.exec(select(models.Camera)).all()),
        }
    print("[setup] seed summary:", counts)
    print("[setup] done. Next: pytest, then uvicorn app.main:app --port 8000")


if __name__ == "__main__":
    ensure_dirs()
    download_wechat_weights()
    init_database()
    print_summary()
