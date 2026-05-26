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
