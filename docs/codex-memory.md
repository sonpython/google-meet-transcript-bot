# Codex Memory

## Project

Google Meet transcript bot for Workspace meetings.

## Current State

- Planning docs created by Claude Code and handed off to Codex.
- Git initialized on `main`.
- Remote: `https://github.com/sonpython/google-meet-transcript-bot.git`
- Remote had no heads/refs when checked on 2026-05-19.
- MVP code is implemented through Phase 8 and verified with offline tests.

## Latest Session

### 2026-06-01 — meet-speaker-activity-hints

Actor: backfilled by Claude Code on 2026-06-11 from git commit `de715ed` (author sonpython).

Done:

- Added `src/bot/speaker_activity_recorder.py`: polls the live Meet UI during recording and writes a speaker-activity timeline JSON next to the audio file.
- Added `src/gemini/speaker_timeline.py`: loads the timeline, merges adjacent segments, and formats per-chunk "Speaker activity hints" text.
- `Transcriber.transcribe()` now accepts `speaker_timeline_path` + `duration_sec` and appends chunk-scoped speaker hints to each Gemini chunk prompt.
- Updated `transcribe_vn_v1.md` prompt: hints are advisory only; audio wins on conflict, fall back to "Người nói A/B".
- Wired through `meeting_session.py`, `recorder_supervisor.py`, `pipeline.py`, `main.py`, and `reprocess_meeting.py`; `MeetingResult` carries the timeline path.

### 2026-05-31 / 2026-06-01 — pdf-export-title-and-metadata

Actor: backfilled by Claude Code on 2026-06-11 from git commits `da12ac8`, `7bc8861` (author sonpython).

Done:

- Meeting Minutes PDF export title now includes meeting title, Meet code, and scheduled start date stamp (`meetingPdfTitle()` in the admin UI script).
- PDF export strips inline `## Generated ...` / `Meet code:` metadata lines from the markdown body and shows the Meet code in the PDF header instead.
- Added `@page` print CSS rules to suppress browser default headers/footers and print a centered page counter.
- All changes in `src/health_server.py` admin UI script only.

### 2026-05-29 — admin-delete-meeting-and-logout

Actor: Codex.

Done:

- Added admin Delete action on meeting detail for non-joining/non-recording meetings.
- Delete removes the meeting row and related admin commands from the DB; generated/audio files are left on disk.
- Scheduler now skips a queued job if its meeting row was deleted before run time.
- Added Settings logout form that expires the admin cookie and redirects to `/admin`.
- Deployed to Docker host `192.168.1.120` and verified container health.

Verification:

- `uv run pytest` -> 86 passed.
- `uv run python -m compileall src tests` -> passed.

### 2026-05-29 — manual-join-scheduled-choice-and-meet-popups

Actor: Codex.

Done:

- Manual Meet add now returns a choice when the Meet code maps to a future scheduled calendar event: join now or join on scheduled time.
- Added `join_scheduled` admin command and scheduler path so manually added future meetings can be queued for their actual start time.
- Manual placeholder meetings refresh their title from the live Meet page after the bot is admitted.
- Added shared Meet popup dismissal for Google Meet/Gemini/AI prompts before join, while waiting for admission, and before screenshots.
- Deployed to Docker host `192.168.1.120` and verified container health.

Verification:

- `uv run pytest` -> 83 passed.
- `uv run python -m compileall src tests` -> passed.

### 2026-05-29 — meeting-minutes-report-template

Actor: Codex.

Done:

- Moved meeting-minutes markdown header generation into `src/gemini/report_template.py`.
- Updated generated meeting-minutes reports so the Meet code appears directly under the generated timestamp instead of as a bullet line.
- Deployed to Docker host `192.168.1.120` and verified container health.

Verification:

- `uv run pytest` -> 79 passed.
- `uv run python -m compileall src tests` -> passed.

### 2026-05-29 — regenerate-transcript-stuck-recovery

Actor: Codex.

Done:

- Investigated latest meeting `ojo-mkpi-hza` stuck at `transcribing 1/1` after a manual transcript regeneration.
- Found admin command `37` left in `running` state across deploy/restart, then reset it once so the worker could retry.
- The retry reached Gemini transcription but did not complete; the old transcript still contained Gemini `503 UNAVAILABLE` high-demand chunk failures.
- Stopped the UI spinner by marking the command and meeting failed with an explicit retry-later error.
- Added startup recovery for interrupted `regenerate` and `regenerate_transcript` admin commands so a service restart cannot leave admin stuck on a stale `running` command.
- Deployed to Docker host `192.168.1.120` and verified container health.

Verification:

- `uv run pytest` -> 79 passed.
- `uv run python -m compileall src tests` -> passed.

### 2026-05-29 — trim-alone-silent-tail

Actor: Codex.

Done:

- Added an audio tail trimmer that checks the post-participant-leave tail with FFmpeg `volumedetect`.
- When Meet exits with reason `alone`, processing now trims the final silent tail before Gemini transcription only if that tail is actually silent.
- Original `.opus` files are kept; Gemini receives a generated `*-trimmed.opus` when trimming succeeds.
- Admin audio playback now defaults to the trimmed audio segment when present and exposes a small dropdown beside Load audio to fetch full original audio including the silent tail.
- Deployed to Docker host `192.168.1.120` and verified container health.

Verification:

- `uv run pytest` -> 78 passed.
- `uv run python -m compileall src tests` -> passed.

### 2026-05-29 — transcript-regeneration-admin-fix

Actor: Codex.

Done:

- Added a separate admin `regenerate_transcript` command and `/admin/api/meetings/{meet_code}/regenerate-transcript` endpoint that rebuilds transcript from retained audio instead of reusing a failed transcript.
- Changed manual meeting-minutes generation to produce only transcript + meeting minutes; summary and combined notes are no longer generated or shown in admin.
- Added a small regenerate-transcript action beside the Transcript copy control in admin.
- Kept screenshot gallery visible in admin and replaced the vague empty state with a config/path hint when no screenshots are found.
- Deployed to Docker host `192.168.1.120` and verified container health.

Verification:

- `uv run pytest` -> 73 passed.
- `uv run python -m compileall src tests` -> passed.

### 2026-05-26 — periodic-meeting-screenshots

Actor: Codex.

Done:

- Added configurable Playwright viewport screenshot capture during admitted meeting recording.
- Default cadence: immediate first capture, then every 300 seconds.
- Default path: `/data/screenshots/<meet-code>/<meet-code>-YYYYMMDDTHHMMSSZ.png`.
- Exposed screenshot metadata in meeting detail API under `files.screenshots`.
- Added admin screenshot gallery with horizontal thumbnails and lightbox navigation.
- Added focused tests for screenshot capture, MeetingSession lifecycle integration, and API metadata.

Notes:

- Capture uses the visible Meet viewport. This prioritizes presentations/screen shares when Google Meet places them on the main stage.

### 2026-05-20 — concurrent-audio-contamination-fix

Actor: Codex.

Done:

- Imported the relevant plan from `~/projects/autogate/plans/260520-1423-meeting-assistant-concurrent-audio-fix/`.
- Fixed the shared PulseAudio sink bug by isolating each live meeting into its own session sink.
- Added regression coverage for explicit recorder source, PulseAudio sink lifecycle, session sink isolation, and job concurrency cap.
- Added `src/tools/reprocess_meeting.py` to regenerate outputs from all audio chunks without re-delivery.
- Deployed to Docker host `192.168.1.120`.
- Repaired affected data:
  - `arq-guqp-pvd` now has 3 audio segments, including the relabeled HeaTech segment.
  - `sch-uuas-hjn` now has only 2 clean EVsafe segments.
  - Small/0-byte sch fragments are quarantined, with full backup retained on host.

Future note:

- Do not route concurrent meetings through `meet_capture.monitor`; use per-session sinks and keep `MAX_CONCURRENT_MEETINGS` bounded.

### 2026-05-20 — autonomous-mvp-implementation

Actor: Codex.

Done:

- Implemented SQLite state, APScheduler recovery/scheduling, Playwright storage-state login support, Meet join/monitor scaffolding, FFmpeg audio recorder, Gemini transcribe/summarize pipeline, Telegram delivery, health checks, LXC/systemd helpers, and tests.
- Ported the Gemini long-audio memory recipe from Claude global memory:
  - chunk audio into 14-minute mono 16kHz MP3 segments;
  - retry across Pro, Flash, and Flash-Lite;
  - detect repeated-line hallucination loops before merge;
  - trust chunk offsets over per-line timestamps.
- Integrated startup validation and randomized daily health check scheduling.
- Verified offline with `uv run pytest` and `uv run python -m compileall src tests`.

Next:

- Run `uv run playwright install chromium` on the target host if browser binaries are missing.
- Configure private `.env`, `client_secrets.json`, encrypted token passphrases, Google OAuth refresh token, and bot storage state.
- Run a real Meet pilot to tune Meet UI selectors and the `meet_capture.monitor` audio source.

### 2026-05-19 — meeting-bot-brainstorm-plan-redteam

Actor: `claude-code-opus-4-7`, then Codex.

Done:

- Brainstormed self-hosted Google Meet transcript pipeline.
- Created 9-phase implementation plan.
- Sanitized real Workspace emails/domain into public placeholders.
- Applied red-team plan changes:
  - PipeWire over PulseAudio.
  - Phase 4 and old Phase 6 merged.
  - Risk-queue denial branch added.
  - Health check randomized.
  - Telegram delivery changed to a combined notes file.
  - YAGNI cuts applied for SQLAlchemy job store, separate audio chunker, `/health`, and external age dependency.

- Phase 1 implementation started:
  - Python project scaffold added.
  - Fernet token store added.
  - Google OAuth user flow added.
  - Calendar API client, classifier, watcher, and entrypoint added.
  - Classifier tests cover organizer, attendee, declined, no-Meet, external, and conferenceData video-entry cases.

Next at that time:

- Run Phase 1 against a real Google OAuth client and real calendar.
- Start Phase 2 SQLite state and APScheduler when requested.
- Keep `docs/session-sync.md` updated after major changes.
- On explicit "export memory", commit and push current memory/docs state after verification.
