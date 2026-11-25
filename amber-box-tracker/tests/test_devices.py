"""Device channel tests: command queue, long-poll, telemetry (PRD-02 section 2.3)."""
from __future__ import annotations

import asyncio

import pytest
from app import devices
from app.db import get_engine, init_db
from app.models import ShelfLight
from app.seed import seed_if_empty
from sqlmodel import Session, select


@pytest.fixture(autouse=True)
def _reset_devices():
    devices.reset()
    yield
    devices.reset()


@pytest.fixture
def session():
    engine = get_engine(":memory:")
    init_db(engine)
    with Session(engine) as s:
        seed_if_empty(s)
        yield s


def test_queue_command_shape_and_colors():
    cmd = devices.queue_command("shelf-light-01", "blink", 30)
    assert cmd == {"cmd": "blink", "color": "blue", "seconds": 30}
    assert devices.queue_command("shelf-light-01", "blink_red", 20)["color"] == "red"
    assert devices.queue_command("shelf-light-01", "ack", 2)["color"] == "green"
    assert devices.queue_command("shelf-light-01", "off", 0)["color"] is None


def test_queue_command_rejects_unknown():
    with pytest.raises(ValueError):
        devices.queue_command("shelf-light-01", "explode", 5)


def test_queue_command_none_device_is_noop():
    assert devices.queue_command(None, "blink", 30) is None


def test_wait_commands_drains_queue_and_updates_telemetry(session):
    devices.queue_command("shelf-light-01", "blink", 30)
    commands = asyncio.run(
        devices.wait_commands(session, "shelf-light-01", wait=0, battery=87.5, rssi=-61)
    )
    assert commands == [{"cmd": "blink", "color": "blue", "seconds": 30}]
    assert devices.pending_commands("shelf-light-01") == []
    light = session.exec(
        select(ShelfLight).where(ShelfLight.device_id == "shelf-light-01")
    ).one()
    assert light.battery == 87.5 and light.rssi == -61
    assert light.last_seen is not None


def test_wait_commands_empty_returns_fast(session):
    commands = asyncio.run(devices.wait_commands(session, "shelf-light-02", wait=0))
    assert commands == []


def test_wait_commands_long_poll_receives_late_command(session):
    async def scenario():
        async def delayed():
            await asyncio.sleep(0.05)
            devices.queue_command("shelf-light-01", "ack", 2)

        task = asyncio.create_task(delayed())
        result = await devices.wait_commands(session, "shelf-light-01", wait=2)
        await task
        return result

    commands = asyncio.run(scenario())
    assert commands == [{"cmd": "ack", "color": "green", "seconds": 2}]


def test_heartbeat_updates_telemetry(session):
    light = devices.update_telemetry(session, "shelf-light-02", battery=50.0, rssi=-70)
    assert light is not None and light.battery == 50.0
    assert devices.update_telemetry(session, "no-such-device") is None


def test_grid_state_maps_shelves_to_devices(session):
    devices.queue_command("shelf-light-01", "blink", 30)
    state = devices.grid_state(session)
    assert set(state["shelves"]) == {"L2-B2", "L2-B3"}
    assert state["shelves"]["L2-B2"]["device_id"] == "shelf-light-01"
    assert state["shelves"]["L2-B2"]["active"]["cmd"] == "blink"
    assert state["shelves"]["L2-B3"]["active"] is None
