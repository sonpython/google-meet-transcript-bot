# Codex Memory

## Project

Google Meet transcript bot for Workspace meetings.

## Current State

- Planning docs created by Claude Code and handed off to Codex.
- Git initialized on `main`.
- Remote: `https://github.com/sonpython/google-meet-transcript-bot.git`
- Remote had no heads/refs when checked on 2026-05-19.
- No application source code has been implemented yet.

## Latest Session

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

Next:

- Start Phase 1 implementation when requested.
- Keep `docs/session-sync.md` updated after major changes.
- On explicit "export memory", commit and push current memory/docs state after verification.
