"""FastAPI entrypoint: lifecycle, static mounts, router wiring (PRD-02 section 2.0).

Startup: init DB + seed, load config/settings.yaml + config/cameras.yaml,
start the not_arrived background task (30 s), start camera workers when
Track 2's app/vision/worker.py is present, mount Track 4's MCP router
(app/amber/mcp_server.py) inside this process when present - architecture B
decision: MCP shares this process so SSE broadcasts and light queues work.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.db import get_engine, init_db
from app.seed import seed_if_empty

BASE_DIR = Path(__file__).resolve().parent.parent
logging.basicConfig(level=os.environ.get("ABT_LOG_LEVEL", "INFO").upper())
log = logging.getLogger("amber.main")

# Live camera worker handles, keyed by camera id (filled when Track 2's
# app/vision/worker.py is importable; cameras report no_signal otherwise).
WORKERS: dict[str, Any] = {}

_settings_cache: dict | None = None
_cameras_cache: list[dict] | None = None


def get_settings() -> dict:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = yaml.safe_load(
            (BASE_DIR / "config" / "settings.yaml").read_text(encoding="utf-8")
        )
    return _settings_cache


def get_camera_configs() -> list[dict]:
    global _cameras_cache
    if _cameras_cache is None:
        data = yaml.safe_load(
            (BASE_DIR / "config" / "cameras.yaml").read_text(encoding="utf-8")
        )
        _cameras_cache = data.get("cameras", [])
    return _cameras_cache


def envelope(
    answer: Any,
    confidence: float,
    sources: list[str],
    needs_human_review: bool = False,
    note: str = "",
) -> dict:
    """Architecture B envelope carried on REST and MCP answers."""
    return {
        "answer": answer,
        "confidence": round(float(confidence), 3),
        "sources": sources,
        "needs_human_review": needs_human_review,
        "note": note,
    }


async def _not_arrived_loop(stop: asyncio.Event) -> None:
    interval = int(get_settings()["rules"]["check_interval_seconds"])
    minutes = int(get_settings()["rules"]["not_arrived_minutes"])
    engine = get_engine()
    while not stop.is_set():
        try:
            with Session(engine) as session:
                from app.rules import check_not_arrived

                check_not_arrived(session, minutes=minutes)
        except Exception:
            log.exception("not_arrived check failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


def _start_camera_workers() -> None:
    """Wire Track 2's worker module when it exists (vision is Track 2's)."""
    try:
        from app.vision import worker as vision_worker
    except ImportError:
        log.info("app.vision.worker not present yet; cameras report no_signal")
        return
    configs = [c for c in get_camera_configs() if c.get("enabled")]
    handles = vision_worker.start_camera_workers(configs, get_engine())
    WORKERS.update(handles or {})


def _mount_mcp(app: FastAPI) -> bool:
    """Mount Track 4's MCP adapter inside this process (their spec):
    build_router(per-request store factory, path='/mcp'), included WITHOUT
    a prefix; handlers stay on the event loop - the broadcaster and device
    queues are shared process state (architecture B transport decision).
    """
    try:
        from app.amber.mcp_http import build_router
    except ImportError:
        log.info("app.amber.mcp_http not present yet; /mcp not mounted")
        return False
    try:
        from app.amber.mcp_http import SqlAmberStore
    except ImportError:
        from app.amber.store import SqlAmberStore  # type: ignore[no-redef]

    mcp_router = build_router(lambda: SqlAmberStore(get_engine()), path="/mcp")
    app.include_router(mcp_router)  # POST /mcp JSON-RPC, no prefix
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    init_db(engine)
    with Session(engine) as session:
        seed_if_empty(session)
    get_settings()
    get_camera_configs()
    _start_camera_workers()
    stop = asyncio.Event()
    task = asyncio.create_task(_not_arrived_loop(stop))
    yield
    stop.set()
    task.cancel()
    for w in list(WORKERS.values()):
        if hasattr(w, "stop"):
            w.stop()
    WORKERS.clear()


def create_app() -> FastAPI:
    app = FastAPI(title="Amber Box Tracker", lifespan=lifespan)

    from app.routers import (
        alerts,
        amber,
        cameras,
        cartons,
        deliveries,
        devices,
        find,
        labels,
        mobile,
    )

    for module in (cameras, alerts, cartons, deliveries, find, mobile, devices, amber, labels):
        app.include_router(module.router)

    _mount_mcp(app)

    web_dir = BASE_DIR / "web"
    snapshots_dir = BASE_DIR / "data" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/snapshots", StaticFiles(directory=snapshots_dir), name="snapshots"
    )
    if web_dir.exists():
        m_page = web_dir / "m.html"
        if m_page.exists():
            @app.get("/m", include_in_schema=False)
            def mobile_page():
                return FileResponse(m_page)

        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
