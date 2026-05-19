---
phase: 2
title: "SQLite State + APScheduler"
status: pending
priority: P1
effort: "0.5d"
dependencies: [1]
---

# Phase 2: SQLite State + APScheduler

## Overview

Persistent SQLite state cho meetings + APScheduler để trigger bot job tại `event.start - 60s`. Idempotent dedupe to avoid double-processing.

## Requirements

**Functional:**
- SQLite schema: `meetings(meet_code TEXT PK, event_id, scheduled_start_utc, title, status, transcript_path, attempts, last_error, created_at, updated_at)`
- Status enum: `scheduled | joining | recording | processing | delivered | failed | cancelled`
- APScheduler: `AsyncIOScheduler`; SQLite `meetings` table is the source of truth for restart recovery
- Idempotency: nếu meet_code đã tồn tại + status terminal → skip; nếu pending → update scheduled time if event moved

**Non-functional:**
- Job schedule survives bot restart by reconstructing jobs from pending SQLite rows
- WAL mode for concurrent read/write safety

## Architecture

```
src/
├── state/
│   ├── db.py                        # SQLite connection, WAL setup
│   ├── meetings_repo.py             # CRUD operations
│   └── migrations/
│       └── 001_init.sql
├── scheduler/
│   └── job_runner.py                # APScheduler wrapper, register bot job per meeting
```

Calendar watcher hooks into scheduler: on qualifying event → `job_runner.schedule_bot(meeting_event)`.

## Related Code Files

**Create:**
- `src/state/db.py`
- `src/state/meetings_repo.py`
- `src/state/migrations/001_init.sql`
- `src/scheduler/job_runner.py`

**Modify:**
- `src/calendar_watcher/watcher.py` (wire to scheduler)
- `src/main.py` (start scheduler)
- `pyproject.toml` (add `apscheduler`)

## Implementation Steps

1. Create migration `001_init.sql` với schema
2. `state/db.py`: connection helper, run migrations on startup, enable WAL
3. `state/meetings_repo.py`:
   - `upsert(meeting_event) -> bool` (returns True if newly scheduled)
   - `mark_status(meet_code, status, error?)`
   - `get_pending() -> list[Meeting]` (recovery on startup)
4. `scheduler/job_runner.py`:
   - `AsyncIOScheduler` with in-memory jobs rebuilt from SQLite on startup
   - `schedule_bot_join(meeting_event)`:
     - run_date = `event.start - 60s` (UTC)
     - job_id = `meet:{meet_code}`
     - misfire_grace_time = 300s
   - On startup: load pending meetings, reschedule future rows, and mark missed rows for operator review
5. Wire watcher: `on_qualifying_event(event) → repo.upsert() → scheduler.schedule_bot_join()`
6. Cancel job logic: detect event cancellation/move via Calendar `updated` watermark → `scheduler.remove_job(meet_code)`

## Success Criteria

- [ ] Restart bot mid-cycle → pending jobs resume correctly
- [ ] Duplicate calendar event → no duplicate job scheduled
- [ ] Event time changed → job rescheduled to new time
- [ ] Event cancelled → job removed
- [ ] Integration test: simulate 3 events (one cancelled, one moved, one new) → state correct

## Risk Assessment

- APScheduler + asyncio: ensure single event loop, avoid blocking calls inside jobs
- SQLite locking: WAL mode mitigates; if issues → switch to async sqlite (`aiosqlite`)
- Clock skew: use UTC everywhere, validate NTP on LXC host
