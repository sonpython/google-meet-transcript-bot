---
phase: 8
title: "Health Checks + systemd + Alerting"
status: pending
priority: P2
effort: "1d"
dependencies: [6, 7]
---

# Phase 8: Health Checks + systemd + Alerting

## Overview

Production hardening: systemd unit, daily health-check job (auto-test bot join), Telegram alerting on failures (3 consecutive threshold), session validity check.

## Requirements

**Functional:**
- systemd unit `meeting-assistant.service` với auto-restart
- Daily health-check job randomized once per day in 05:00-09:00 Asia/Saigon:
  - Spawn bot, attempt join dedicated test Meet room
  - Validate audio capture (2s buffer > 1KB)
  - Send Gemini ping (1 token test)
  - Send Telegram ping (silent test message)
  - Report pass/fail to Telegram
- Failure alerting via Telegram:
  - Threshold: 3 consecutive failures of same type → alert
  - Types: join_failed, audio_failed, gemini_failed, telegram_failed, session_expired
- Startup tasks:
  - Validate token store readable
  - Validate Playwright storageState valid (non-expired)
  - Resume any pending scheduled meetings

**Non-functional:**
- Logs persisted via journald
- Restart policy: on-failure with 10s backoff, max 5/min
- No silent failures — everything logs

## Architecture

```
src/
├── health/
│   ├── daily_check.py               # daily self-test workflow
│   ├── alerter.py                   # consecutive failure threshold logic
│   └── startup_validation.py
infra/systemd/
└── meeting-assistant.service
```

## Related Code Files

**Create:**
- `src/health/__init__.py`
- `src/health/daily_check.py`
- `src/health/alerter.py`
- `src/health/startup_validation.py`
- `infra/systemd/meeting-assistant.service`
- `infra/systemd/install.sh`

**Modify:**
- `src/main.py` (schedule daily-check job, run startup validation)
- `src/state/db.py` (add `failures(component, count, last_at)` table)

## Implementation Steps

1. **systemd unit `meeting-assistant.service`:**
   ```ini
   [Unit]
   Description=Meeting Assistant Bot
   After=network-online.target pipewire.service
   Wants=network-online.target

   [Service]
   Type=simple
   User=meetbot
   WorkingDirectory=/opt/meeting-assistant
   ExecStartPre=/opt/meeting-assistant/infra/scripts/audio-healthcheck.sh
   ExecStart=/opt/meeting-assistant/.venv/bin/python -m src.main
   Restart=on-failure
   RestartSec=10s
   StartLimitInterval=60s
   StartLimitBurst=5
   EnvironmentFile=/etc/meeting-assistant/env

   [Install]
   WantedBy=default.target
   ```
2. **startup_validation.py:**
   - Token store decryptable? → fail fast if no
   - Playwright storageState exists + non-empty?
   - Probe Google session (load myaccount.google.com headless) → flag if redirects to login
   - Gemini API key valid? (test call)
   - Telegram bot reachable? (`getMe` API call)
   - Report any failures via Telegram
3. **daily_check.py:**
   - Scheduled via APScheduler with one randomized run time per day in 05:00-09:00 Asia/Saigon
   - Workflow:
     a. Spawn bot session
     b. Join `<TEST_MEET_CODE>` (user creates dedicated test room, always-open)
     c. Record 5s audio, validate file size
     d. Stub Gemini call (transcribe 5s) — verify response
     e. Send Telegram message: "✅ Daily health check pass" or "❌ Failure: <component>"
     f. Cleanup test recording
4. **alerter.py:**
   - `record_failure(component) -> alert?: bool`
   - Tracks consecutive failures per component in SQLite
   - Returns `True` (triggering Telegram alert) when count == 3
   - `record_success(component)` resets counter
5. Wire failure tracker into all stages (joiner, recorder, gemini, telegram)
6. **install.sh:** copy systemd unit, enable + start service

## Success Criteria

- [ ] systemd unit starts on boot
- [ ] Crash → auto-restart within 10s
- [ ] Startup validation catches expired storageState
- [ ] Daily randomized health check runs, reports pass to Telegram
- [ ] Simulate 3 consecutive join failures → alert sent exactly once
- [ ] After 1 success → counter resets, alerts re-armed
- [ ] journald logs structured JSON, queryable

## Risk Assessment

- Daily test meeting room: user must create one and keep it open. Randomized schedule reduces repetitive automation signature but does not remove bot-detection risk.
- Alert fatigue: 3-fail threshold may be too low if transient errors common. Tunable via env
- Recursive failure: if alerter fails (Telegram down) → fallback log to file, alert on next success
- systemd unit on Proxmox LXC: ensure `Type=simple` works in container (no fork issues)
