# Session Sync

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
