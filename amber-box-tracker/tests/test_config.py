"""Config contract tests: settings.yaml and cameras.yaml must match the PRDs."""
from __future__ import annotations

from pathlib import Path

import yaml
from app import models
from app.db import get_engine, init_db
from app.seed import seed_if_empty
from sqlmodel import Session, select

BASE_DIR = Path(__file__).resolve().parent.parent


def load_yaml(rel: str) -> dict:
    return yaml.safe_load((BASE_DIR / rel).read_text(encoding="utf-8"))


def test_settings_contract():
    s = load_yaml("config/settings.yaml")
    assert s["qr"]["payload_pattern"] == "^KYC1:[A-Z0-9]{6}$"
    assert s["aruco"]["dictionary"] == "DICT_4X4_50"
    assert s["detector"]["classes"] == ["cardboard box", "person"]
    assert s["rules"]["check_interval_seconds"] == 30
    assert s["rules"]["not_arrived_minutes"] == 2
    assert s["performance"]["min_fps_per_camera"] == 5
    assert 0 < s["privacy"]["head_blur_fraction"] <= 0.5
    assert s["devices"]["long_poll_max_seconds"] <= 25


def test_cameras_yaml_matches_seeded_cameras():
    cfg = load_yaml("config/cameras.yaml")
    entries = {c["id"]: c for c in cfg["cameras"]}
    assert set(entries) == {"CAM-GATE", "CAM-HOIST-3", "CAM-AISLE-2", "CAM-POV"}
    assert entries["CAM-POV"]["source_type"] == "push"
    for entry in entries.values():
        assert entry["enabled"] is True
        assert entry["fps_process"] >= 1

    engine = get_engine(":memory:")
    init_db(engine)
    with Session(engine) as session:
        seed_if_empty(session)
        for cam in session.exec(select(models.Camera)).all():
            assert cam.id in entries
            if entries[cam.id]["source_type"] == "file":
                assert entries[cam.id]["source"] == cam.source
