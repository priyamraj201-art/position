# Track 1 State — Platform, DB, Rules, Alerts & Devices (Integration Owner)

- **Owner**: Shivam + Agent 1
- **Branch**: `feat/track-1-core-platform` (PR #6), `feat/track-1-config-setup` (PR 1b)
- **Status**: WAVE_1_IN_PROGRESS
- **Current Task**: Wave 1 done (PR 1a + 1b open) — Wave 2 next: `app/rules.py`, `app/alerts.py`, `app/devices.py`, `app/main.py`, `app/routers/*`
- **Last Completed**: PR 1a (models.py, db.py, seed.py, seed.json, requirements.txt — 6 tests green) + PR 1b (config/settings.yaml, config/cameras.yaml, .env.example, scripts/setup.py — 8 tests green, setup.py verified end-to-end)
- **Blockers**: None
- **Next Sync**: Post `[MERGE-POINT-1]` on GitHub Tracking Issue #1 once PR 1a lands on `main` (Track 4's real-DB tests unblock then).

### Checklist
- [x] `amber-box-tracker/requirements.txt` (with `opencv-contrib-python-headless==4.10.0.84` guard) + `.env.example`
- [x] `config/settings.yaml` & `config/cameras.yaml`
- [x] `data/seed.json` & `app/models.py` & `app/db.py` & `app/seed.py`
- [x] `scripts/setup.py`
- [ ] `app/rules.py` & `app/alerts.py` + `tests/test_rules.py`
- [ ] `app/devices.py` + `tests/test_devices.py`
- [ ] `app/main.py` & `app/routers/*` & `app/vision/worker.py` wiring
