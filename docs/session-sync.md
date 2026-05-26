# Session Sync

## 2026-05-26 — periodic-meeting-screenshots

Status: implemented locally and awaiting deployment.

Code changes:

- Added `src/bot/screenshot_capturer.py`.
- `MeetingSession` starts screenshot capture only after join success and recording start, then stops it during cleanup before browser close.
- New settings:
  - `SCREENSHOT_DIR=/data/screenshots`
  - `SCREENSHOT_CAPTURE_ENABLED=true`
  - `SCREENSHOT_INTERVAL_SECONDS=300`
- Meeting detail API now includes captured screenshots under `files.screenshots`.
- Admin meeting detail now shows screenshots as a horizontal thumbnail strip. Clicking opens a lightbox with previous/next controls, keyboard arrows, Escape close, and mobile swipe.
- README runtime flow documents the screenshot capture behavior.

Verification:

- `uv run pytest tests/test_public_api.py tests/test_screenshot_capturer.py tests/test_session_sink_isolation.py` -> 11 passed.
- `uv run pytest` -> 70 passed.
- `uv run python -m compileall src tests` -> passed.
- `uv build` -> passed.

## 2026-05-20 — concurrent-audio-contamination-fix

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified.

Root cause:

- Overlapping meetings were routed through the shared PulseAudio sink `meet_capture.monitor`.
- `sch-uuas-hjn` captured a HeaTech segment that belonged to `arq-guqp-pvd`.

Code changes:

- Added per-meeting PulseAudio null sinks via `src/runtime_audio.py`.
- `MeetingSession` now creates `meet_capture_<meet_code>`, launches Chromium with `PULSE_SINK=<sink>`, records `<sink>.monitor`, and unloads the sink in `finally`.
- `AudioRecorder.start()` accepts an explicit `audio_source`.
- `JobRunner` now wraps meeting runs with a configurable concurrency cap, default `MAX_CONCURRENT_MEETINGS=3`.
- Added `src/tools/reprocess_meeting.py` for idempotent transcript/summary/minutes/notes rebuild from all audio segments.

Data repair on host:

- Backup created: `/opt/meeting-assistant/data/backups/audio.bak-20260520T073657Z` and matching DB backup.
- Moved `sch-uuas-hjn.opus` to `arq-guqp-pvd-20260520T030500Z.opus`.
- Quarantined small/0-byte `sch-uuas-hjn` fragments under `data/audio/quarantine-20260520-concurrent-fix/`.
- Reprocessed:
  - `arq-guqp-pvd` from 3 audio segments.
  - `sch-uuas-hjn` from 2 clean EVsafe segments.

Verification:

- `uv run pytest` -> 47 passed.
- `python -m compileall src` -> passed.
- Docker container healthy.
- API reports `arq-guqp-pvd` delivered with 3 audio segments and `sch-uuas-hjn` delivered with 2 audio segments.
- Grep found no HeaTech terms (`Viện Nhi`, `E-Host`, `FPT`, `Patient App`, `DX30`) in EVsafe transcript/minutes.

## 2026-05-20 — autonomous-mvp-implementation

Status: MVP implemented and offline verified. Live pilot remains pending because it needs real Google OAuth, bot account login, audio device routing, Gemini API key, and Telegram credentials.

Files touched or created:

- `pyproject.toml`
- `.env.example`
- `README.md`
- `src/config.py`
- `src/main.py`
- `src/state/*`
- `src/scheduler/*`
- `src/bot/*`
- `src/gemini/*`
- `src/telegram_sender/*`
- `src/health/*`
- `scripts/bot_first_login.py`
- `infra/scripts/*`
- `infra/systemd/*`
- `infra/proxmox/lxc-config.conf`
- `tests/test_gemini_pipeline.py`
- `tests/test_meetings_repo.py`
- `tests/test_telegram_formatter.py`
- `tests/test_health.py`

Verification:

- `uv run pytest` -> 19 passed.
- `uv run python -m compileall src tests` -> passed.

Next handoff target:

- Configure private runtime secrets and run a live pilot meeting.
- If Meet UI changed, tune selectors in `src/bot/meet_selectors.py` and `src/bot/meet_joiner.py`.
- If LXC audio source differs, update `meet_capture.monitor` usage in `src/bot/audio_recorder.py`.

## 2026-05-19 — meeting-bot-brainstorm-plan-redteam

Status: handoff prepared for Codex execution.

Files touched or created:

- `README.md`
- `AGENTS.md`
- `.gitignore`
- `plans/260519-2134-meeting-transcript-pipeline/plan.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-01-scaffolding-oauth-calendar.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-02-sqlite-state-scheduler.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-03-playwright-login-storagestate.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-04-playwright-meet-join.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-05-pipewire-ffmpeg-audio-capture.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-06-gemini-transcribe-summarize.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-07-telegram-delivery.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-08-health-checks-systemd.md`
- `plans/260519-2134-meeting-transcript-pipeline/phase-09-pilot-tune.md`
- `plans/reports/brainstorm-260519-2103-meeting-transcript-pipeline.md`
- `plans/reports/red-team-260519-meeting-bot.md`

Next handoff target:

- Validate Phase 1 with real Google OAuth credentials and then implement Phase 2.

Verification before push:

- Sensitive grep gates must pass.
- Confirm no `.env`, credentials, audio, data, or `.codex/` files are staged.
