"""API smoke tests across the Track 1 routers (PRD-02 section 2.2)."""
from __future__ import annotations

import io

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    import app.db as db_module

    db_module._engine = None
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    import app.main as main_module

    monkeypatch.setattr(main_module, "_settings_cache", None)
    monkeypatch.setattr(main_module, "_cameras_cache", None)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_cameras_list_no_signal_without_vision(client):
    data = client.get("/api/cameras").json()
    assert len(data["cameras"]) == 4
    assert all(c["status"] == "no_signal" for c in data["cameras"])
    assert data["cameras"][0]["fps"] == 0


def test_mjpeg_503_without_worker(client):
    response = client.get("/api/cameras/CAM-GATE/mjpeg")
    assert response.status_code == 503


def test_cartons_list_and_kyc1_prefix_locate(client):
    data = client.get("/api/cartons").json()
    assert len(data["cartons"]) == 8
    from app import devices

    devices.reset()
    response = client.post("/api/cartons/KYC1:BV2401/locate")
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]["shelf"] == "L2-B2"
    assert body["answer"]["light_command"]["cmd"] == "blink"
    assert body["confidence"] == 1.0
    assert devices.pending_commands("shelf-light-01") == [
        {"cmd": "blink", "color": "blue", "seconds": 30}
    ]
    devices.reset()


def test_locate_unknown_carton_404(client):
    assert client.post("/api/cartons/ZZ9999/locate").status_code == 404


def test_deliveries_status_from_sightings(client):
    data = client.get("/api/deliveries").json()
    by_id = {d["id"]: d for d in data["deliveries"]}
    assert set(by_id) == {"DEL-2211", "DEL-2190"}
    assert len(by_id["DEL-2211"]["expected"]) == 6
    assert by_id["DEL-2211"]["seen"] == []
    assert len(by_id["DEL-2211"]["missing"]) == 6


def test_receive_then_confirm_short(client):
    response = client.post("/api/deliveries/DEL-2211/receive")
    assert response.json()["received"] == 6
    data = client.get("/api/deliveries").json()
    del2211 = {d["id"]: d for d in data["deliveries"]}["DEL-2211"]
    assert len(del2211["seen"]) == 6
    response = client.post(
        "/api/deliveries/DEL-2211/confirm",
        json={"confirm": True, "missing": ["DM0402"]},
    )
    body = response.json()
    assert body["short_delivery"]["missing"] == ["DM0402"]
    alerts = client.get("/api/alerts?type=short_delivery").json()["alerts"]
    assert len(alerts) == 1
    resolve = client.post(
        f"/api/alerts/{alerts[0]['id']}/resolve", json={"note": "supplier notified"}
    )
    assert resolve.json()["status"] == "resolved"


def test_find_fuzzy_and_envelope(client):
    body = client.get("/api/find", params={"q": "AHU-3 damper"}).json()
    codes = {m["label_code"] for m in body["answer"]["matches"]}
    assert {"DM0401", "DM0402"} <= codes
    assert body["confidence"] >= 0.6
    assert body["sources"]
    miss = client.get("/api/find", params={"q": "zzzzqqqq"}).json()
    assert miss["answer"]["matches"] == []
    assert miss["needs_human_review"] is True


def test_find_accepts_kyc1_prefix(client):
    body = client.get("/api/find", params={"q": "KYC1:BV2401"}).json()
    assert body["answer"]["matches"][0]["label_code"] == "BV2401"


def test_device_commands_roundtrip(client):
    from app import devices

    devices.reset()
    devices.queue_command("shelf-light-01", "blink", 30)
    data = client.get("/api/devices/shelf-light-01/commands?wait=0&battery=90&rssi=-55").json()
    assert data["commands"] == [{"cmd": "blink", "color": "blue", "seconds": 30}]
    grid = client.get("/api/devices/grid-state").json()
    assert grid["shelves"]["L2-B2"]["battery"] == 90.0
    hb = client.post(
        "/api/devices/shelf-light-02/heartbeat", json={"battery": 55.0}
    ).json()
    assert hb["ok"] is True
    devices.reset()


def test_damage_report_via_api(client):
    response = client.post(
        "/api/mobile/damage",
        data={"carton_code": "KYC1:DM0402", "note": "dented"},
        files={"file": ("d.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 32), "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]["carton"] == "DM0402"
    alerts = client.get("/api/alerts?type=damaged").json()["alerts"]
    assert len(alerts) == 1


def test_pov_upload_stores_proof_flags_review(client):
    response = client.post(
        "/api/mobile/pov-upload/DEL-2211",
        files={"file": ("clip.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")},
    )
    body = response.json()
    assert body["needs_human_review"] is True
    assert "proof" in body["answer"]


def test_carton_timeline(client):
    client.post("/api/deliveries/DEL-2211/receive")
    data = client.get("/api/cartons/BV2401/timeline").json()
    assert data["label_code"] == "BV2401"
    assert isinstance(data["sightings"], list)


def test_carton_labels_pdf(client):
    response = client.get("/api/labels/cartons.pdf", params={"delivery_id": "DEL-2211"})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_amber_chat_returns_provider_contract(client):
    """Track 4's provider (PR #3) answers /api/amber/chat with the chat
    contract: reply, tool_calls, needs_confirmation."""
    response = client.post("/api/amber/chat", json={"message": "where is BV2401"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["reply"], str) and body["reply"]
    assert isinstance(body["tool_calls"], list)
    assert body["needs_confirmation"] is False


def test_pov_upload_scans_proof_and_marks_seen(client, tmp_path):
    """Positive POV path: a clip carrying KYC1:BV2401 counts that carton as seen."""
    cv2 = pytest.importorskip("cv2")
    qrcode = pytest.importorskip("qrcode")

    qr = qrcode.make("KYC1:BV2401").convert("RGB")
    frame = cv2.cvtColor(
        __import__("numpy").array(qr.resize((480, 480))), cv2.COLOR_RGB2BGR
    )
    clip = tmp_path / "proof.mp4"
    writer = cv2.VideoWriter(
        str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (480, 480)
    )
    if not writer.isOpened():
        pytest.skip("cv2 VideoWriter unavailable in this environment")
    for _ in range(10):
        writer.write(frame)
    writer.release()

    with open(clip, "rb") as fh:
        response = client.post(
            "/api/mobile/pov-upload/DEL-2211",
            files={"file": ("proof.mp4", fh, "video/mp4")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == 1.0
    assert "BV2401" in body["answer"]["seen"]
    assert "BV2401" not in body["answer"]["missing"]


def test_device_commands_empty_longpoll_returns_empty(client):
    """3.10 regression: an empty long poll must time out into [], not a 500."""
    response = client.get("/api/devices/shelf-light-01/commands", params={"wait": 0.2})
    assert response.status_code == 200
    assert response.json() == {"commands": []}
