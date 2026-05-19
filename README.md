# Google Meet Transcript Bot

Status: in planning.

This project plans a self-hosted Google Meet transcript pipeline for Workspace meetings:

1. Watch Google Calendar for qualifying Meet events.
2. Join meetings with a transparent bot account.
3. Capture meeting audio inside a Proxmox LXC.
4. Transcribe Vietnamese audio with Gemini.
5. Send a combined transcript and summary to a Telegram group.

## Planned Stack

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

The plan is intentionally still pre-implementation. The first implementation phase is project scaffolding plus Google Calendar OAuth.

## Required Accounts And Secrets

Use environment variables or private secret files only. Do not commit credentials.

- `USER_EMAIL=user@your-domain.com`
- `BOT_EMAIL=bot@your-domain.com`
- Google OAuth desktop client secret
- Gemini API key
- Telegram bot token and chat ID
- Fernet passphrase for local token encryption

## Notes

Google Meet automation has operational risk. The plan includes explicit fallback paths for self-hosted Vexa or Recall.ai if Playwright admission becomes unreliable.
