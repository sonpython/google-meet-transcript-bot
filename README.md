# Google Meet Transcript Bot

Status: MVP implementation complete for offline/local verification. Real Workspace OAuth, bot login, audio device, Gemini, and Telegram credentials are still required for a live pilot.

This project plans a self-hosted Google Meet transcript pipeline for Workspace meetings:

1. Watch Google Calendar for qualifying Meet events.
2. Join meetings with a transparent bot account.
3. Capture meeting audio inside a Proxmox LXC.
4. Transcribe Vietnamese audio with Gemini.
5. Send a combined transcript and summary to a Telegram group.

## Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 |
| Browser | Playwright + Chromium |
| Audio | PipeWire + FFmpeg |
| Scheduler | APScheduler |
| State | SQLite |
| AI | Gemini multimodal audio |
| Delivery | Telegram Bot API |

## Current Plan

The implementation plan lives in:

- `plans/260519-2134-meeting-transcript-pipeline/plan.md`
- `plans/reports/brainstorm-260519-2103-meeting-transcript-pipeline.md`
- `plans/reports/red-team-260519-meeting-bot.md`

Phases 1-8 are implemented in code. Phase 9 is a live pilot and needs real credentials plus a real Google Meet to tune UI selectors and audio routing.

## Development

Install dependencies:

```bash
uv sync --dev
```

Install browser binaries on a fresh machine:

```bash
uv run playwright install chromium
```

Run tests:

```bash
uv run pytest
uv run python -m compileall src tests
```

Run first-time bot browser login and save encrypted Playwright storage state:

```bash
uv run python scripts/bot_first_login.py
```

Run the watcher after configuring `.env` and `client_secrets.json`:

```bash
uv run python -m src.main
```

The first Calendar OAuth run opens a browser and stores the refresh token encrypted at `TOKEN_STORE_PATH`. The bot account login is separate and uses `scripts/bot_first_login.py`.

## Required Accounts And Secrets

Use environment variables or private secret files only. Do not commit credentials.

- `USER_EMAIL=user@your-domain.com`
- `BOT_EMAIL=bot@your-domain.com`
- Google OAuth desktop client secret
- Gemini API key
- Telegram bot token and chat ID
- Fernet passphrase for local token encryption

See `.env.example` for the full runtime configuration.

## Runtime Flow

1. Calendar watcher finds Meet events where `USER_EMAIL` is organizer or accepted attendee.
2. SQLite stores meeting state and APScheduler schedules the bot to join about 60 seconds before start.
3. Playwright launches Chromium with encrypted bot storage state and joins Meet transparently as `BOT_DISPLAY_NAME`.
4. FFmpeg records the configured Pulse/PipeWire monitor source to an Opus file.
5. Gemini pipeline chunks audio into 14-minute mono 16kHz MP3 segments, retries across `gemini-2.5-pro`, `gemini-2.5-flash`, and `gemini-2.5-flash-lite`, rejects repeated-line hallucination loops, then writes transcript, summary, and combined notes.
6. Telegram sends an inline TL;DR plus the full notes markdown document when Telegram settings are configured.
7. Startup validation and randomized daily health checks verify token, storage state, Gemini, and Telegram availability.

## Deployment Notes

Infrastructure helpers live under `infra/`:

- `infra/scripts/setup-lxc.sh` installs system packages for Debian-based LXC hosts.
- `infra/scripts/audio-healthcheck.sh` validates audio capture prerequisites.
- `infra/systemd/meeting-assistant.service` is the production service template.
- `infra/systemd/install.sh` installs/enables the service after paths and env files are prepared.

Docker deployment for the current host is documented in `docs/deployment.md`.

## Notes

Google Meet automation has operational risk. The plan includes explicit fallback paths for self-hosted Vexa or Recall.ai if Playwright admission becomes unreliable.
