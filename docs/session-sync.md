# Session Sync

## 2026-06-11 — bot-session-reauth-and-keepalive-alerting

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy (`bot_session_keepalive_ok`).

Incident notes:

- Session signed out since 2026-06-09 10:33 UTC; Google Workspace web-session policy expires after 14 days (`passive=1209600` in signin URL).
- Headless password reauth lands on `signin/confirmidentifier` + verification challenge, unrecoverable without a human; keepalive retried every 15 min for ~2 days.
- Re-auth pitfall: `$(ssh host "grep STORAGE_PASSPHRASE ...")` captured iTerm2 shell-integration escape sequences from the host shell, producing a 239-char contaminated passphrase → `InvalidToken` on the container. Extract with printf markers (`@@...@@` + sed) instead.
- Restart pitfall: two quick `docker compose restart` runs left a stale PulseAudio pid file (`pa_pid_file_create() failed`) → crashloop. Use `docker compose up -d --force-recreate`.

Code changes:

- `src/bot/session_keepalive.py`: notifier support (`send_text`), alert on failed-reauth with 6h cooldown, recovery message, pause password reauth after `MAX_CONSECUTIVE_REAUTH_FAILURES=3` consecutive failures.
- `src/main.py`: pass `discord_client or telegram_client` as keepalive notifier (bypasses `health_notify_enabled` gate; session-out is critical).
- New `scripts/bot_reauth_local.py`: headed login, waits on `myaccount.google.com` host (not substring — `continue=` param contains it), validates SID cookie before saving encrypted state.
- New `scripts/deploy-to-host.sh`: tar-pipe sync + `docker compose up -d --build`.
- `docs/deployment.md`: re-auth runbook + permanent fix via Google Admin session control ("Session never expires" for bot OU).

Verification:

- `uv run pytest` -> 92 passed (4 new keepalive tests).
- `uv run python -m compileall src tests` -> passed.
- Deploy via `scripts/deploy-to-host.sh`; `bot_session_keepalive_ok` logged on new build; `/status` reports `state=running`.

Open items:

- Google Admin session-control change ("Session never expires" for the bot account OU) must be done manually in admin.google.com — not yet applied.

## 2026-06-01 — meet-speaker-activity-hints (backfilled 2026-06-11)

Status: committed as `de715ed` and running in production; entry backfilled by Claude Code from git history.

Code changes:

- New `src/bot/speaker_activity_recorder.py` polls Meet UI for active speaker names during recording, writes timeline JSON beside the audio file (`speaker_timeline_path()`).
- New `src/gemini/speaker_timeline.py` loads hints, merges adjacent segments, formats per-chunk hint text.
- `Transcriber` appends chunk-scoped speaker hints to Gemini prompts; `transcribe_vn_v1.md` marks hints advisory-only (audio wins on conflict).
- Plumbed via `meeting_session.py`, `recorder_supervisor.py`, `pipeline.py`, `main.py`, `reprocess_meeting.py`; `MeetingResult` gained timeline path field.
- Tests added: `tests/test_speaker_activity_recorder.py` plus updates in pipeline/recorder/session tests.

## 2026-05-31 / 2026-06-01 — pdf-export-title-and-metadata (backfilled 2026-06-11)

Status: committed as `da12ac8` + `7bc8861` and running in production; entry backfilled by Claude Code from git history.

Code changes (all in `src/health_server.py` admin UI script):

- `meetingPdfTitle()` / `pdfDateStamp()`: PDF download title = doc type + meeting title + Meet code + start date stamp.
- `stripPdfMetadata()` removes `## Generated ...` and `Meet code:` lines from exported markdown; Meet code rendered in PDF header line instead.
- `jsArg()` helper for safely passing JS string args in inline onclick handlers.
- `@page` print CSS suppresses browser headers/footers, adds centered page number.

## 2026-05-29 — admin-delete-meeting-and-logout

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy.

Code changes:

- Added `MeetingsRepo.delete_meeting()`.
- Added `POST /admin/api/meetings/{meet_code}/delete`.
- Admin detail now shows a Delete button unless the meeting is currently `joining` or `recording`.
- Delete removes the admin history record and related admin commands but keeps existing files on disk.
- `JobRunner` checks the DB row before executing a scheduled job, so deleted future meetings do not still run.
- Settings page now includes a Logout form posting to `/admin/logout`; the server clears the `admin_token` cookie.

Verification:

- `uv run pytest` -> 86 passed.
- `uv run python -m compileall src tests` -> passed.
- Docker deploy: `docker compose up -d --build meeting-assistant` on `192.168.1.120`.
- Runtime check: container `meeting-assistant` healthy; `/status` reports `state=running`.

## 2026-05-29 — manual-join-scheduled-choice-and-meet-popups

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy.

Code changes:

- `POST /admin/api/manual-join` accepts `mode=join_now|scheduled`.
- If a manually entered Meet code resolves to a future calendar event and no mode is provided, the API returns `needs_schedule_choice`.
- Admin UI shows Join now and Join on scheduled time options for that case.
- Added `join_scheduled` admin command and scheduler handling.
- Manual placeholder meeting titles are refreshed from the live Meet page after admission.
- Added `src/bot/meet_popups.py` and call it before join, during admission polling, and before each screenshot capture to dismiss Google Meet/Gemini/AI prompt dialogs.

Verification:

- `uv run pytest` -> 83 passed.
- `uv run python -m compileall src tests` -> passed.
- Docker deploy: `docker compose up -d --build meeting-assistant` on `192.168.1.120`.
- Runtime check: container `meeting-assistant` healthy; `/status` reports `state=running`.

## 2026-05-29 — meeting-minutes-report-template

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy.

Code changes:

- Added `src/gemini/report_template.py` for shared meeting-minutes report title/marker formatting.
- Changed the generated meeting-minutes marker from:
  `## Generated ...` plus `- Meet code: ...`
  to:
  `## Generated ...` plus `Meet code: ...`.
- Existing reports are not rewritten automatically; newly generated minutes use the new format.

Verification:

- `uv run pytest` -> 79 passed.
- `uv run python -m compileall src tests` -> passed.
- Docker deploy: `docker compose up -d --build meeting-assistant` on `192.168.1.120`.
- Runtime check: container `meeting-assistant` healthy; `/status` reports `state=running`.

## 2026-05-29 — regenerate-transcript-stuck-recovery

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy.

Incident notes:

- Latest meeting `ojo-mkpi-hza` showed `transcribing 1/1` after the user clicked transcript regeneration.
- DB showed `admin_commands.id=37` and the meeting processing state were both `running`, but the service had restarted after that timestamp, so the command was stale.
- After resetting the command to `pending`, the worker picked it up, but Gemini transcription did not complete and the retained transcript still showed `503 UNAVAILABLE` high-demand failures.
- The command and meeting were marked `failed` with an explicit retry-later error so admin no longer spins indefinitely.

Code changes:

- Added `_recover_interrupted_admin_commands()` in `src/main.py`.
- On startup, any `admin_commands.status='running'` is marked failed as `interrupted by service restart`.
- For `regenerate` and `regenerate_transcript`, the related meeting processing state is also marked failed so the admin UI leaves the running state.
- Added regression coverage in `tests/test_admin_manual_join.py`.

Verification:

- `uv run pytest` -> 79 passed.
- `uv run python -m compileall src tests` -> passed.
- Docker deploy: `docker compose up -d --build meeting-assistant` on `192.168.1.120`.
- Runtime check: container `meeting-assistant` healthy; `/status` reports `state=running`.

## 2026-05-29 — trim-alone-silent-tail

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy.

Code changes:

- Added `src/bot/audio_tail_trimmer.py`.
- Meeting processing now handles `alone` exits by checking the audio tail after the participant-leave timestamp.
- Tail validation uses FFmpeg `volumedetect`; if max volume stays under the silence threshold, it writes `*-trimmed.opus` and sends that to Gemini.
- If tail is not silent, too short, or trimming fails, processing keeps the original audio.
- Admin audio metadata now filters `*-trimmed.opus` out as a duplicate segment and uses it as the default replacement for the matching original segment.
- Admin audio player shows a small dropdown beside Load audio when a trimmed segment exists; the dropdown reloads audio metadata/playback with `mode=full` to include the original silent tail.
- Added tests for silent-tail trim/keep behavior and MeetingSession using the trimmed audio path.

Verification:

- `uv run pytest` -> 78 passed.
- `uv run python -m compileall src tests` -> passed.
- Docker deploy: `docker compose up -d --build meeting-assistant` on `192.168.1.120`.
- Runtime check: container `meeting-assistant` healthy; `/status` reports `state=running`.

## 2026-05-29 — transcript-regeneration-admin-fix

Status: implemented, deployed to `192.168.1.120:/opt/meeting-assistant`, and verified healthy.

Code changes:

- Added admin transcript regeneration:
  - API: `POST /admin/api/meetings/{meet_code}/regenerate-transcript`
  - DB command: `regenerate_transcript`
  - Worker path forces re-transcription from retained `.opus` audio and clears stale minutes/summary references.
- Changed existing `regenerate`/Generate minutes path so it only generates `meeting-minutes-*.md` from the current transcript. It no longer calls summary generation or writes combined notes.
- Admin detail now renders only Meeting Minutes and Transcript document blocks.
- Transcript block has a regenerate button next to copy.
- Screenshots section now shows an explicit empty-state hint if no screenshot files are discoverable under configured `SCREENSHOT_DIR`.

Verification:

- `uv run pytest` -> 73 passed.
- `uv run python -m compileall src tests` -> passed.
- Docker deploy: `docker compose up -d --build meeting-assistant` on `192.168.1.120`.
- Runtime check: container `meeting-assistant` healthy; `/status` reports `state=running`.

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
