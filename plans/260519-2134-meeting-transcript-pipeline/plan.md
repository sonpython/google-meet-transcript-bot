---
title: "Meeting Transcript Pipeline (Playwright Bot)"
status: implemented_offline
priority: P1
created: 2026-05-19
source: brainstorm
sourceDoc: plans/reports/brainstorm-260519-2103-meeting-transcript-pipeline.md
blockedBy: []
blocks: []
---

# Meeting Transcript Pipeline — Implementation Plan

## Summary

Single-branch Playwright bot trong Proxmox LXC tự động join Google Meet meeting đủ điều kiện của `user@your-domain.com`, capture audio, transcribe Vietnamese qua Gemini, deliver combined `.md` transcript + structured summary tới Telegram group.

**Source brainstorm:** `plans/reports/brainstorm-260519-2103-meeting-transcript-pipeline.md`

## Architecture

```
Calendar Watcher → Bot Orchestrator (Playwright + PipeWire + FFmpeg in LXC)
       ↓                        ↓
  SQLite state           audio.opus file
                                ↓
                       Gemini 2.5 Pro (VN transcript + summary)
                                ↓
                       Telegram Bot delivery
```

## Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 |
| Browser | Playwright Python + Chromium headless |
| Audio | PipeWire + FFmpeg |
| Container | Proxmox LXC Debian 12 unprivileged |
| Scheduler | APScheduler |
| Telegram | python-telegram-bot v22 |
| DB | SQLite |
| AI | Gemini 2.5 Pro (multimodal audio) |

## Key Accounts

- `user@your-domain.com` — Workspace user (NOT admin), OAuth scope `calendar.readonly`
- `bot@your-domain.com` — Workspace Business Starter seat ($6/mo), Playwright login

## Phases

| # | Phase | Effort | Status |
|---|---|---|---|
| 1 | [Scaffolding + OAuth + Calendar Watcher](phase-01-scaffolding-oauth-calendar.md) | 1d | implemented |
| 2 | [SQLite state + APScheduler](phase-02-sqlite-state-scheduler.md) | 0.5d | implemented |
| 3 | [Playwright login + storageState](phase-03-playwright-login-storagestate.md) | 1d | implemented |
| 4 | [Playwright Meet join + exit handoff](phase-04-playwright-meet-join.md) | 2.5d | implemented_offline |
| 5 | [PipeWire + FFmpeg audio capture](phase-05-pipewire-ffmpeg-audio-capture.md) | 2d | implemented_offline |
| 6 | [Gemini transcribe + summarize](phase-06-gemini-transcribe-summarize.md) | 1.5d | implemented_offline |
| 7 | [Telegram delivery + formatting](phase-07-telegram-delivery.md) | 0.5d | implemented |
| 8 | [Health checks + systemd + alerting](phase-08-health-checks-systemd.md) | 1d | implemented |
| 9 | [Pilot + tuning](phase-09-pilot-tune.md) | 1-2d | pending_live_credentials |

**Total:** ~11-12 dev days

## Key Dependencies

- Phase 2 → 1 (state needed after calendar watcher)
- Phase 3 → 1 (OAuth context for bot login)
- Phase 4 → 3 (login required before join)
- Phase 5 → infrastructure parallel with Phase 3-4
- Phase 6 → 4, 5 (audio handoff produces input)
- Phase 7 → 6 (delivery after transcribe)
- Phase 8 → 6, 7 (production hardening)
- Phase 9 → all (integration test)

## Decisions Locked

See Section 8 of brainstorm doc. Key:
- Single-branch Playwright (no Workspace recording dependency)
- Bot identity: "Meeting Note-taker (bot)" via `bot@your-domain.com`
- Filter: events with `hangoutLink` where user@your-domain.com invited, not declined
- Vietnamese transcript + structured summary (TL;DR/Decisions/Actions/Next Steps)
- MVP: queue concurrent meetings (no parallel bots)
- Alert threshold: 3 consecutive fails
- Daily health check: randomized window 05:00-09:00 Asia/Saigon
- Path B if Playwright risk-queue blocks admission: evaluate self-hosted Vexa.
- Path C if self-build economics stop making sense: Recall.ai at roughly $0.50/hour plus transcription/storage fees.

## Success Criteria

- ≥95% coverage of qualifying calendar events
- ≥95% bot admission rate (your-domain.com domain)
- p50 ≤8 min latency post-meeting → Telegram
- ≥90% transcript accuracy (manual review 10 meetings)
- ≥99% uptime over 30 days
- ≤$15/month operating cost

## Risks (top 3)

1. Google Meet risk-queue or UI updates block Playwright join (High) → stealth mitigations, diagnostic status, Vexa/Recall fallback path
2. PipeWire/LXC audio instability (Med) → audio device passthrough validation + boot check
3. Bot account flagged (Low-Med) → real Workspace seat, transparent name, no spam
