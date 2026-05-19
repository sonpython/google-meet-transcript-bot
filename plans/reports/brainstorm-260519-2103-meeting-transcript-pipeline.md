# Brainstorm Report — Meeting Transcript Pipeline

**Date:** 2026-05-19 21:03 GMT+7 (updated 21:35)
**Decision:** Single-branch architecture — Playwright bot trong Proxmox LXC join MỌI meeting user được mời (host + attend), bypass Workspace recording entirely
**Status:** Design approved — ready for planning

---

## 1. Problem Statement

User wants automated system that:
1. Watches Google Calendar for upcoming Meet events
2. Bot tự động join mọi meeting `user@your-domain.com` được mời (attendee or organizer)
3. Capture audio, generate Vietnamese transcript + structured summary qua Gemini
4. Delivers to Telegram group: `.md` file + inline summary

**Constraints:**
- Google Workspace (your-domain.com) — user account: `user@your-domain.com`
- User NOT super admin → cannot config domain-wide delegation or shared-drive policy
- Most meetings: assistant hosts; user attends. External-host meetings out of scope (chỉ your-domain.com)
- Vietnamese language primary
- Self-hosted on Proxmox homelab (24/7)
- Bot consent OK (visible name "Meeting Note-taker")
- Post-meeting delivery acceptable
- No SaaS dependency
- Volume: 10-30h/month meetings

---

## 2. Approaches Evaluated

| Approach | Verdict | Reason |
|---|---|---|
| Workspace native recording (Drive watcher) | ❌ Rejected | Recording lands in HOST's Drive (assistant). User not admin → cannot setup domain-wide delegation / shared drive policy without coordinating với admin. Friction cao |
| Workspace + assistant shares Drive folder manually | ❌ Rejected | Per-user setup, fragile khi có host khác. Pollution của Drive |
| Recall.ai SaaS bot | ❌ Rejected | Third-party data path; 2026 pricing is much lower than initially assumed, so keep as fallback |
| **Self-built Playwright bot (single code path)** | ✅ **CHOSEN** | Free, full control, không phụ thuộc Workspace admin, uniform handling cho mọi meeting |

**Key rationale:** Self-built bot dù fragile (Meet UI changes) nhưng:
- Architecture đơn giản hơn hybrid (1 branch thay vì 2)
- Không cần phối hợp với Workspace admin
- Maintenance ~4h/month chấp nhận được vs SaaS $180+/mo
- Bot transparent (visible trong participant list với tên rõ ràng)

---

## 3. Final Solution — Single-Branch Architecture

### 3.1 Data flow

```
┌──────────────────────────────────────────────┐
│ Google Calendar (user@your-domain.com events)   │
└────────────────────┬─────────────────────────┘
                     │ poll every 5min
                     ▼
┌──────────────────────────────────────────────┐
│ Calendar Watcher                             │
│ - filter: event has hangoutLink              │
│ - filter: user@your-domain.com in attendees     │
│ - dedupe in SQLite                           │
│ - schedule bot job: event.start - 1 min      │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ Bot Orchestrator (Proxmox LXC)               │
│ ┌──────────────────────────────────────────┐ │
│ │ Playwright + Chromium (headless)         │ │
│ │ - login as bot@your-domain.com                 │ │
│ │ - join Meet URL, name "Meeting Note-taker (bot)"    │ │
│ │ - handle waiting room                    │ │
│ │ - detect admission / kicked / ended      │ │
│ └──────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────┐ │
│ │ PipeWire virtual sink + FFmpeg         │ │
│ │ - capture meeting audio → .opus          │ │
│ └──────────────────────────────────────────┘ │
└────────────────────┬─────────────────────────┘
                     │ audio file (.opus)
                     ▼
┌──────────────────────────────────────────────┐
│ Gemini 2.5 Pro                               │
│ - transcribe Vietnamese + speaker diarization│
│ - structured summary (TL;DR/Decisions/Actions│
│   /Next Steps)                               │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ Telegram Bot                                 │
│ - inline: title, time, duration, TL;DR       │
│ - attachment: meeting-notes-<date>-<slug>.md │
└────────────────────┬─────────────────────────┘
                     ▼
        ┌──────────────────────────┐
        │ Telegram group (private) │
        └──────────────────────────┘
```

### 3.2 Components

**(a) Calendar Watcher**
- Poll Calendar API every 5 min, look ahead 1h
- Filter:
  - Event có `hangoutLink` (Meet URL)
  - `user@your-domain.com` ∈ `attendees[].email` HOẶC `organizer.email == user@your-domain.com`
  - `responseStatus != "declined"` (skip declined)
- Dedupe: SQLite `meetings(meet_code, event_id, scheduled_start, status, transcript_path)`
- Schedule job at `event.start - 60s` via APScheduler
- On cancel/update: detect via Calendar `updated` watermark, cancel pending job

**(b) Bot Orchestrator (Playwright + Chromium in LXC)**
- LXC container: Debian 12, unprivileged, audio passthrough
- Stack:
  - Playwright Python (Chromium)
  - PipeWire (`module-null-sink`)
  - FFmpeg (capture PipeWire monitor → `.opus`)
- Flow:
  1. Job fires at event.start - 60s
  2. Launch Chromium with `--use-fake-ui-for-media-stream`, route audio to null-sink
  3. Navigate to `https://accounts.google.com` → login `bot@your-domain.com` (saved auth state file)
  4. Navigate to `meet.google.com/<meet-code>`
  5. Set display name "Meeting Note-taker (bot)" trong pre-join screen
  6. Click "Ask to join" (mic/cam off)
  7. Wait for admission (max 5 min) — detect by URL change or DOM
  8. On admit: start FFmpeg capture → `/tmp/<meet-code>.opus`
  9. Poll every 30s:
     - "You've been removed from the meeting" → exit
     - participant count = 1 (only bot) for >2 min → exit
     - meeting URL changed / page closed → exit
     - max duration 4h hard cap
  10. On exit: SIGINT FFmpeg, hand off `.opus` + metadata to Gemini step
- Failure modes:
  - Login expired → refresh via stored refresh token, alert if persistent
  - Not admitted in 5 min → log + Telegram alert
  - Audio device unavailable → fail fast + alert

**(c) Bot Account `bot@your-domain.com`**
- Separate Workspace Business Starter seat ($6/mo)
- Pre-added as attendee on meetings via Calendar API (optional optimization to auto-admit)
- Saved Playwright `storageState.json` for cookies/session
- Email visible to participants → transparent recording signal

**(d) Gemini Transcribe + Summarize**
- Model: Gemini 2.5 Pro (multimodal audio)
- Input: `.opus` audio file
- Output 1 — transcript (VN, speaker diarization, ~30s timestamps)
- Output 2 — structured summary:
  ```
  ## TL;DR
  (2-3 sentences)

  ## Decisions
  - …

  ## Action Items
  - [ ] <person> — <task> — <deadline if mentioned>

  ## Next Steps
  - …
  ```
- Skip meetings <2 min
- Chunk meetings >2h (30 min slices, 10s overlap)

**(e) Telegram Bot**
- Inline message: meeting title, datetime, duration, TL;DR (<800 chars)
- Attach `transcript-<YYYYMMDD-HHMM>-<slug>.md`
- chat_id + bot token from env (user has)

**(f) Storage**
- SQLite `/data/meeting-assistant.db` for state
- Audio files purged after Gemini success
- Telegram message = source of truth (no separate archive)

### 3.3 Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 |
| Container | Proxmox LXC (Debian 12, unprivileged) |
| Auth — user | OAuth desktop (`calendar.readonly`) |
| Auth — bot | Playwright storageState + manual login refresh |
| Scheduler | APScheduler |
| Browser | Playwright Python + Chromium |
| Audio | PipeWire + FFmpeg |
| Telegram | python-telegram-bot v21 |
| DB | SQLite |

---

## 4. Implementation Considerations

### 4.1 Prereqs (user action)

1. Provision `bot@your-domain.com` Workspace Business Starter seat (~$6/mo)
2. Manual first login on dev machine → save Playwright `storageState.json`
3. Google Cloud project: enable Calendar API + Gemini API, OAuth client for user@your-domain.com
4. Telegram bot token + group chat_id (already have)
5. Proxmox LXC: provision Debian 12 container, enable audio device passthrough

### 4.2 OAuth scopes
- user@your-domain.com: `calendar.readonly` (chỉ cần xem events)
- bot@your-domain.com: no Google API scopes — chỉ login Google web để join Meet

### 4.3 Bot admission strategy
- Default: bot clicks "Ask to join" — host approves
- Optimization: Calendar Watcher auto-adds `bot@your-domain.com` to attendees list 5 min before meeting start → Workspace meetings auto-admit known org members
- Fallback: 3 retries if not admitted, then alert

### 4.4 Edge cases
- Concurrent meetings (overlap) → queue or scale to 2-3 LXC bot instances. MVP: queue, alert user về meeting skipped
- Meeting cancelled <60s before start → check before launching
- Meet code changes (organizer regenerates) → re-fetch from Calendar before bot launch
- Bot kicked mid-meeting → save partial audio, process anyway, flag trong summary
- Network blip during meeting → FFmpeg buffer survives short drops, Playwright reconnect
- Login session expired → automatic refresh via stored cookies; if fails, Telegram alert
- Meeting goes >4h → hard cap, save what we have, note "truncated"
- DST / timezone bugs → store everything UTC, convert for display

### 4.5 Privacy & security
- OAuth tokens: encrypted file (Fernet)
- Playwright storageState: chmod 600 + encrypted at rest
- Telegram token in env
- Audio files local-only, purged after Gemini success
- Bot identity transparent ("Meeting Note-taker (bot)") + bot@your-domain.com visible email
- No Drive uploads, no third-party data path

---

## 5. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Google Meet UI update breaks Playwright | **High** | High | Stable selectors (aria-label). Daily health-check: launch bot vào test meeting, alert on fail. Maintenance budget ~4h/mo |
| Bot not admitted to meetings | Med | Med | Auto-add bot as attendee via Calendar API. 3 retries + alert |
| PipeWire flaky in LXC | Med | High | Test audio passthrough on provision, healthcheck on boot |
| Bot account flagged by Google (suspicious activity) | Low-Med | High | Real Workspace seat (paid), transparent name, no spam joins, normal user-agent |
| Gemini Vietnamese accuracy weak | Low-Med | High | Pilot 5-10 meetings. Fallback: self-hosted Whisper large-v3 |
| Concurrent meetings | Med | Med | MVP: queue + skip + alert. Phase 2: scale bot instances |
| LXC downtime missed meetings | Med | Med | systemd auto-restart, healthcheck. Tolerate occasional miss |
| Meeting >2h Gemini context limit | Med | Med | Audio chunking with overlap |
| Telegram message >4096 chars | High | Low | Summary luôn là attachment, inline chỉ TL;DR |
| Login session expires unexpectedly | Med | Med | Detect on launch, refresh, alert if needed |
| User declined event but pipeline still runs | Low | Low | Filter `responseStatus != "declined"` |

**Maintenance cost accepted:** ~4h/month fixing UI selectors. Recall.ai is now documented as a lower-cost fallback at roughly $0.50/hour plus add-ons, not the original high-cost assumption.

---

## 6. Success Metrics

- **Coverage:** ≥95% of calendar Meet events có user@your-domain.com → Telegram delivery
- **Bot admission rate:** ≥95% (your-domain.com domain meetings auto-admit)
- **Latency:** p50 ≤8 min post-meeting → Telegram, p95 ≤15 min
- **Transcript quality:** ≥90% accuracy on key decisions/names (manual review 10 meetings)
- **Uptime:** ≥99% over 30 days
- **Cost:** ≤$15/month (Gemini API + bot Workspace seat $6)
- **Maintenance:** UI-break incidents tracked, fix turnaround <24h

---

## 7. Next Steps

### Immediate (user)
1. Provision `bot@your-domain.com` Workspace seat
2. Provide Google Cloud project access OR allow new project creation
3. Confirm Telegram bot token + chat_id ready
4. Provision Proxmox LXC với audio passthrough

### Dev phases (planned via `/ck:plan`)
- **Phase 1** — Project scaffolding + OAuth + Calendar Watcher (1 day)
- **Phase 2** — SQLite state + APScheduler integration (0.5 day)
- **Phase 3** — Playwright bot: login flow + storageState management (1 day)
- **Phase 4** — Playwright bot: Meet join logic + waiting room handling + exit handoff (2.5 days)
- **Phase 5** — PipeWire + FFmpeg audio capture in LXC (2 days, includes infra setup)
- **Phase 6** — Gemini transcribe + summarize integration + VN prompt tuning (1.5 days)
- **Phase 7** — Telegram delivery + formatting (0.5 day)
- **Phase 8** — Health checks, systemd units, daily test meeting, alerting (1 day)
- **Phase 9** — Pilot 5-10 real meetings + tune (1-2 days)

**Total:** ~11-12 dev days

### Optional post-MVP
- Concurrent meeting support (parallel bot LXCs)
- Search across transcripts (embeddings + vector DB)
- Speaker name resolution from calendar attendees
- Action item export (Todoist/Notion)
- Live transcript via Gemini Live API

---

## 8. Decisions Locked

| Question | Decision |
|---|---|
| User account | user@your-domain.com (Workspace) |
| Workspace admin access | No, user not admin — avoid admin-dependent solutions |
| Telegram | Group + bot ready, env vars only |
| Long-term archive | None — Telegram message = source of truth |
| Meeting filter | All meetings user@your-domain.com invited to (host + attend), within your-domain.com |
| External-host meetings | Out of scope (assistant hosts those instead) |
| Bot strategy | Single-branch self-built Playwright bot (no Workspace recording dependency) |
| Volume estimate | 10-30h/mo |
| Bot identity | `bot@your-domain.com` separate Workspace seat |
| Transcript timing | Post-meeting OK |
| Language | Vietnamese primary |
| Summary structure | TL;DR + Decisions + Action Items + Next Steps |

---

## 9. Open Questions

1. Proxmox node có audio device passthrough capability không (cần verify trước khi LXC setup)?
2. Concurrent meeting frequency — có thường xảy ra không? MVP queue OK hay cần scale ngay?
3. Alert threshold — Telegram alert mỗi fail hay batch (vd 3 consecutive fails)?
4. Daily health check time — chạy lúc nào trong ngày (vd 6h sáng)?
