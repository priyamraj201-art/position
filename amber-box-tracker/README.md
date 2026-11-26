# Amber Box Tracker

Tracks delivered cartons from the gate to the right shelf. Cameras and phone/glasses video read the
QR label on each carton. Amber, the site assistant, alerts on wrong floor, wrong shelf, short
delivery, damage and cartons that never arrive, and answers questions like "where is BV2401?".

Runs on a normal laptop, CPU only. Sample data only (Harbor Point Medical Office).

> Status: Amber, the MCP adapter and the API tests are merged and tested on Python 3.10
> (107 tests). Not yet checked on Python 3.11, with real cameras, or on the ESP32 hardware.

## Setup

Needs Python 3.11 and about 1 GB of free disk for model weights.

```bash
cd amber-box-tracker
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
python scripts/setup.py     # downloads weights, creates data/app.db, loads data/seed.json
uvicorn app.main:app --host 0.0.0.0 --port 8000 --env-file .env
```

Open http://localhost:8000 for the dashboard.

**OpenCV rule.** The project needs `opencv-contrib-python-headless==4.10.0.84` (it has the WeChat QR
and ArUco code). Never install `opencv-python` next to it. `ultralytics` pulls it in anyway, and pip
cannot exclude transitive deps, so `python scripts/setup.py` removes the intruder and
force-reinstalls the pinned contrib build automatically. To fix an environment by hand:

```bash
pip uninstall -y opencv-python opencv-python-headless
pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.10.0.84
```

**Amber keys (optional).** Put `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` in `.env`. The app does not read `.env` itself, so start
uvicorn with `--env-file .env` (as above) or export the variable in your shell. With neither set,
or if the SDK is missing, Amber uses the offline provider. Keys are never committed.

## Amber assistant

Amber answers in one or two spoken sentences and always uses tools. It never guesses a floor or
shelf.

| Tool | Purpose |
| :-- | :-- |
| `find_carton` | Fuzzy search by label code, part number, name or PO. `auto_locate` lights the shelf. |
| `where_does_this_go` | Destination floor and shelf of a carton. |
| `delivery_status` | Expected, seen and missing cartons of a delivery. |
| `report_damage` | Two steps: asks to confirm, then records the damage and an alert. |
| `list_open_alerts` | Summary of open alerts. |

Offline phrases (no network): `where is <x>`, `find <x>`, `light up <x>`, `blink <x>`, `show <x>`,
`light it up` (the carton from the last find), `where does <code> go`, `status of DEL-2211`,
`<code> is damaged: <note>`, `open alerts`.

Damage needs confirmation. The chat call returns `needs_confirmation: true`. Send the same message
again with `confirm: true` to record it. The model can never confirm for itself.

## MCP adapter (submission-facing)

`app/amber/mcp_server.py` is a thin MCP adapter (standard library only). It adds no storage or
rules: each tool calls `app/amber/tools.py` over the app's SQLite data (`app/amber/sql_store.py`,
which uses `app/alerts.py` and `app/devices.py`) and wraps the result as
`{answer, confidence, sources, needs_human_review, note}`. Confidence and review rules are in
`app/amber/envelope.py`.

**Transport.** `app/amber/mcp_http.py` is mounted in `app/main.py` as `POST /mcp` (JSON-RPC over
HTTP, no SSE, no sessions). It runs inside the app so shelf-light commands and live alerts share the
app's in-memory queues.

**Client check.** The official Python MCP SDK 1.30.0 (`streamablehttp_client`) was run once against a
live uvicorn on Python 3.10: `initialize`, `tools/list` (7 tools) and two `tools/call` requests
worked. Other SDK versions and other MCP clients are untested.

`python -m app.amber.mcp_server` (stdio) exists for local development only. It runs in a separate
process, so lights and live alerts do not reach the running app. Do not use it for the submission.

Tools: `find_carton`, `where_does_this_go`, `delivery_status`, `report_damage`,
`list_open_alerts`, and the optional `list_cartons` and `resolve_alert` (needs a note written by a
person). `report_damage` never records through MCP: it returns `needs_human_review: true` and a
person confirms in the app. `delivery_status` counts a carton as seen if it has a sighting or a received time, the same rule as
`/api/deliveries`.

## Demo with no hardware (3 minutes)

1. `python scripts/setup.py`, then start the server. Open the dashboard.
2. **Short delivery (0:00).** `python scripts/run_on_video.py --video videos/01_gate_pov.mp4 --camera CAM-POV`.
   Expect a `short_delivery` alert listing `DM0402`.
3. **Wrong floor (0:45).** Run `videos/02_wrong_floor.mp4` on `CAM-HOIST-3`. Expect one
   `wrong_floor` alert for `BV2401`, with a toast within 2 s on the Live tab.
4. **Wrong shelf (1:30).** Run `videos/03_shelf.mp4` on `CAM-AISLE-2`. Expect `wrong_shelf` when
   `DM0401` rests at `L2-B3`, then auto-resolved and `stored` when it moves to `L2-B2`.
5. **Ask Amber (2:15).** Ask "where is AHU-3 dampers", then "light it up". The Virtual Shelf Grid
   blinks, and the simulator prints `BLINK` for `shelf-light-01`:
   `python firmware/shelf-light/sim.py --device shelf-light-01 --server http://localhost:8000`.
6. **Phone (2:40).** Open `https://<laptop-LAN-IP>:8000/m` on Android Chrome, scan a printed label,
   hear the destination.

Print labels from `/api/labels/cartons.pdf` and shelf markers from `/api/labels/shelves.pdf`.

## HTTPS for the phone page (`/m`)

Browsers only allow the camera over HTTPS (or localhost). Make a local certificate, for example with
[mkcert](https://github.com/FiloSottile/mkcert):

```bash
mkcert -install
mkcert 192.168.1.50            # your laptop's LAN IP
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --ssl-keyfile 192.168.1.50-key.pem --ssl-certfile 192.168.1.50.pem
```

The phone must trust the mkcert root CA, or accept the browser warning once. Phone and laptop must
be on the same Wi-Fi.

## Recording guide

For the real-video test and for glasses/phone clips:
- Film the QR label flat-on, 1.5 to 3 m away, in good light. Hold still for a second.
- Keep labels at least 4 cm wide in the frame. Do not cover the corners.
- Shelf markers (ArUco) must be visible in the same frame as the carton for wrong-shelf checks.
- Record 720p or 1080p, 15 to 30 fps, `.mp4`. Put files in `videos/` and add them to
  `config/cameras.yaml` as `file:videos/<name>.mp4`.
- Faces: the app blurs the top 35% of every detected person in saved snapshots. Do not film people
  who have not agreed.

## ESP32 shelf light (optional)

Confirmed against Track 3's merged `firmware/shelf-light/include/config.h`. Set your own Wi-Fi
values in a local config and do not commit them.

| From | To |
| :-- | :-- |
| ESP32-C3 GPIO4 | 330 ohm resistor, then WS2812B DIN |
| 5V and GND | LED strip, with a 1000 uF capacitor across 5V and GND |
| ESP32-C3 GPIO5 | passive buzzer `+`, buzzer other leg to GND |

Board: `esp32-c3-devkitm-1` (PlatformIO). Set `WIFI_SSID`, `WIFI_PASS`, `SERVER`, `DEVICE_ID` in
`config.h`. Without hardware, use `sim.py` and the Virtual Shelf Grid, which behave the same.

## Licences and policies

- Ultralytics YOLO models are AGPL-3.0. That is acceptable for this hackathon prototype. Kaya's
  production stack uses RF-DETR (Apache-2.0) for commercial use.
- Meta glasses: in production, QR decoding of glasses frames happens on the device, within Meta's
  acceptable-use policy. This prototype uses a phone camera or recorded clips instead.

## Tests

```bash
pytest
```

Amber tests need no network and no API keys. Full acceptance run: `python scripts/setup.py`, `pytest`,
`run_on_video.py` on the three synthetic videos, then the server (plus the HTTPS check for `/m`).
Target: at least 5 FPS per camera with 3 cameras on CPU.

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| QR never decodes | Check the OpenCV rule above. Without WeChat weights the app falls back to the basic detector, which is weaker. |
| `/m` camera blocked | Use HTTPS (see above). |
| No weights download | Rerun `scripts/setup.py` on a network that allows GitHub. The offline fallbacks keep the app running. |
| Amber says "Try: where is..." | The offline provider did not recognise the phrase. Use the phrases listed above. |
| Camera tile says "no signal" | The video path in `config/cameras.yaml` is wrong or missing. |
| Low FPS | Lower `fps_process` in `config/settings.yaml`, or use `imgsz=640` on non-aisle cameras. |

## Deviations from the PRDs

None yet. Track 4 will list any here.
