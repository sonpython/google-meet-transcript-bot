---
phase: 1
title: "Scaffolding + OAuth + Calendar Watcher"
status: implemented
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Scaffolding + OAuth + Calendar Watcher

## Overview

Bootstrap Python 3.12 project, setup OAuth desktop flow cho `user@your-domain.com` (scope `calendar.readonly`), implement Calendar API watcher poll mỗi 5 min lookahead 1h.

## Requirements

**Functional:**
- Python 3.12 project với `uv` package manager
- OAuth desktop client → exchange refresh token, store encrypted with `cryptography.fernet`
- Poll Google Calendar API every 5 min, lookahead 1h
- Filter events: `hangoutLink` present + user@your-domain.com is organizer OR attendee with `responseStatus != "declined"`
- Emit `MeetingEvent` dataclass (meet_code, event_id, start_utc, title, organizer, attendees)

**Non-functional:**
- All files <200 lines
- Logging via `structlog` (JSON, file + journald)
- No secrets in code/env — encrypted token store

## Architecture

```
src/
├── main.py                          # entrypoint, starts scheduler
├── auth/
│   ├── oauth_user.py                # user OAuth flow + token refresh
│   └── token_store.py               # Fernet-encrypted token persistence
├── calendar_watcher/
│   ├── client.py                    # Google Calendar API wrapper
│   ├── classifier.py                # filter logic, MeetingEvent emission
│   └── watcher.py                   # poll loop integration
├── models/
│   └── meeting_event.py             # dataclass
└── config.py                        # env loader (pydantic-settings)
```

## Related Code Files

**Create:**
- `pyproject.toml` (uv project, Python 3.12)
- `src/main.py`
- `src/config.py`
- `src/auth/oauth_user.py`
- `src/auth/token_store.py`
- `src/calendar_watcher/client.py`
- `src/calendar_watcher/classifier.py`
- `src/calendar_watcher/watcher.py`
- `src/models/meeting_event.py`
- `.env.example`
- `README.md`

**Created:**
- `tests/test_calendar_classifier.py`

## Implementation Steps

1. Init `uv` project: `uv init --python 3.12`, add deps: `google-auth-oauthlib`, `google-api-python-client`, `pydantic-settings`, `structlog`, `cryptography`
2. Create Google Cloud project, enable Calendar API, create OAuth Desktop client → download `client_secrets.json`
3. Implement `auth/oauth_user.py`:
   - First-run flow: open browser, exchange code → refresh token
   - Subsequent: load + refresh access token
4. Implement `auth/token_store.py`:
   - Encrypt token with Fernet key derived from env `TOKEN_PASSPHRASE`
   - Store at `/data/tokens/user-token.fernet`
5. Implement `calendar_watcher/client.py`:
   - `list_upcoming(window_minutes=60)` → returns Calendar events with `hangoutLink`
6. Implement `calendar_watcher/classifier.py`:
   - Filter logic in pure function: `is_qualifying(event, user_email) -> bool`
7. Implement `calendar_watcher/watcher.py`:
   - Async poll loop (5 min interval) → emit `MeetingEvent` to handler callback
8. `src/main.py`: glue + structlog config + signal handlers (SIGTERM, SIGINT)
9. Write README with first-run OAuth instructions

## Success Criteria

- [ ] `uv run python -m src.main` starts, OAuth first-run completes
- [ ] Token stored encrypted, survives restart (refresh works)
- [ ] Watcher logs qualifying events from real calendar
- [x] Unit tests for `classifier.is_qualifying` (5 fixtures: organizer/attendee/declined/no-meet/external)

## Risk Assessment

- OAuth setup gotcha: redirect URI mismatch → document `http://localhost:8765` in client config
- Calendar API quota: default 1M/day, polling = 288 calls/day → safe
- Token encryption: derive a stable Fernet key from `TOKEN_PASSPHRASE`; fail fast if the env var is missing
