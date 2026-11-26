# Track 3 State — Dashboard UI, Mobile POV (/m) & ESP32 Firmware

- **Owner**: Yashwant + Agent 3
- **Branch**: `feat/track-3-wave-2-integration`
- **Status**: WAVE_2_COMPLETE
- **Current Task**: Completed Wave 2 deliverables. Live FastAPI endpoints, WebSockets, multipart video/damage uploads, grid polling, and device commands verified. Ready for Wave 3 integration.
- **Last Completed**:
  - Wired `web/app.js` and `amber-box-tracker/web/app.js` to live FastAPI endpoints (`/api/cameras`, `/api/alerts`, `/api/alerts/stream`, `/api/cartons`, `/api/cartons/{code}/timeline`, `/api/deliveries`, `/api/find`, `/api/devices/grid-state`).
  - Added real-time Virtual Shelf Grid polling to sync hardware device commands with UI pulse animations.
  - Wired `web/m.html` and `amber-box-tracker/web/m.html` to live `/ws/pov` WebSocket (4 FPS JPEG binary streaming), multipart `/api/mobile/pov-upload/{id}`, multipart `/api/mobile/damage`, and delivery confirmations.
  - Verified `firmware/shelf-light/sim.py` polling and animation against live Track 1 `/api/devices/{id}/commands` queue.
- **Blockers**: None.
- **Next Sync**: Ready for Wave 3 full-pipeline acceptance with synthetic and real video streams (`[TRACK-3 -> INTEGRATION] [HANDOFF]`).

### Checklist
- [x] `web/styles.css` (dark projector-ready theme + Virtual Shelf Grid pulse animations)
- [x] `web/index.html` + `web/app.js` (Live MJPEG, Alerts SSE + toast + speech, Cartons timeline, Receive, Find + Virtual Grid, Amber panel)
- [x] `web/m.html` (HTTPS `getUserMedia` + `WS /ws/pov` 4 fps, POV video upload, Damage report, Hold-to-talk Amber voice)
- [x] `firmware/shelf-light/` (`platformio.ini`, `include/config.h`, `src/main.cpp` for ESP32-C3 + WS2812B + buzzer)
- [x] `firmware/shelf-light/sim.py` (terminal shelf-light simulator verified against live `/api/devices/{id}/commands`)
- [x] Wave 2 live endpoint wiring & verification
