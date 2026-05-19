---
phase: 4
title: "Playwright Meet Join + Exit Handoff"
status: implemented_offline
priority: P1
effort: "2.5d"
dependencies: [3]
---

# Phase 4: Playwright Meet Join + Exit Handoff

## Overview

Implement bot join flow, risk-queue diagnostics, in-meeting monitoring, clean audio stop, and audio handoff to the Gemini pipeline.

## Requirements

**Functional:**
- Navigate to `meet.google.com/<meet-code>` from pre-join screen
- Set display name "Meeting Note-taker (bot)" trong pre-join name input
- Mic OFF, Cam OFF before clicking join
- Click "Ask to join" / "Join now" (depending on host setup)
- Wait for admission (max 5 min) — detect via DOM (`[aria-label*="Leave"]` button appears OR participant list visible)
- Handle outcomes: admitted / denied / risk_queue_denied / timeout / network error
- Poll meeting state every 30s after admission:
  - removed/kicked dialog → exit reason `kicked`
  - meeting ended dialog OR URL change to homepage → exit reason `ended`
  - participant count = 1 for >2 min → exit reason `alone`
  - max duration 4h → exit reason `hard_cap`
- On exit: stop FFmpeg cleanly, capture final `.opus` path, update SQLite to `processing`
- Emit `MeetingResult(meet_code, audio_path, duration_sec, exit_reason, participant_names)`

**Non-functional:**
- All selectors centralized in `meet_selectors.py` (single point of update khi Google đổi UI)
- Screenshots on failure for debugging
- Bot retries pre-join up to 3 times nếu page fail load
- Graceful cleanup on every exit path: close browser, stop recorder, persist partial audio if present

## Architecture

```
src/
├── bot/
│   ├── meet_joiner.py               # join flow state machine
│   ├── meet_selectors.py            # all CSS/aria selectors (single point of update)
│   ├── join_result.py               # result dataclass (admitted/denied/timeout/risk_queue_denied)
│   ├── meet_monitor.py              # poll loop while joined
│   ├── participant_tracker.py       # extract participant list from DOM
│   ├── exit_detector.py             # detect kicked/ended/alone/hard cap
│   └── meeting_session.py           # orchestrates joiner + recorder + monitor
```

States: `LAUNCHING → PRE_JOIN → REQUESTING_JOIN → WAITING_ROOM → ADMITTED | DENIED | RISK_QUEUE_DENIED | TIMEOUT`

## Related Code Files

**Create:**
- `src/bot/meet_joiner.py`
- `src/bot/meet_selectors.py`
- `src/bot/join_result.py`
- `src/bot/meet_monitor.py`
- `src/bot/participant_tracker.py`
- `src/bot/exit_detector.py`
- `src/bot/meeting_session.py`
- `src/models/meeting_result.py`

**Modify:**
- `src/scheduler/job_runner.py` (job invokes `MeetingSession.run`)
- `src/state/meetings_repo.py` (status updates)

## Implementation Steps

1. `meet_selectors.py`:
   ```python
   NAME_INPUT = 'input[aria-label*="name" i]'
   MIC_TOGGLE = '[aria-label*="microphone" i][role="button"]'
   CAM_TOGGLE = '[aria-label*="camera" i][role="button"]'
   ASK_TO_JOIN_BTN = 'button:has-text("Ask to join")'
   JOIN_NOW_BTN = 'button:has-text("Join now")'
   LEAVE_BTN = '[aria-label*="leave call" i]'
   DENIED_TEXT = 'text="No one responded to your request"'
   RISK_QUEUE_TEXT = 'text=/suspicious|automated|could not be verified/i'
   REMOVED_DIALOG = 'text="You\\'ve been removed"'
   MEETING_ENDED = 'text="You left the meeting"'
   PARTICIPANT_LIST_BTN = '[aria-label*="participant" i]'
   PARTICIPANT_NAMES = '[data-participant-id]'
   ```
2. `meet_joiner.py`:
   - `async join(context, meet_code, display_name, timeout=300) -> JoinResult`
   - Steps:
     a. `page.goto(f'https://meet.google.com/{meet_code}')`
     b. Wait for either pre-join name input OR direct join button
     c. Fill name (if input visible)
     d. Ensure mic + cam OFF (check aria-pressed/state)
     e. Click "Ask to join" or "Join now"
     f. Wait race: `LEAVE_BTN` (success) | `DENIED_TEXT` (denied) | `RISK_QUEUE_TEXT` (risk_queue_denied) | timeout
     g. Return `JoinResult(status, joined_at, error_msg)`
3. `participant_tracker.py`:
   - `async get_participants(page) -> list[str]`: open participant panel, extract names
4. `exit_detector.py`:
   - `async check_exit_signal(page) -> ExitReason | None`
   - Check in order: removed/kicked, ended, page closed, participant_count=1 sustained
5. `meet_monitor.py`:
   - Poll loop async every 30s
   - Maintain `alone_since` timestamp
   - Emit exit reason when detected
6. `meeting_session.py`:
   ```python
   async def run(meeting_event):
       repo.mark_status(meet_code, 'joining')
       session = await browser_session.launch_with_state()
       join_result = await meet_joiner.join(session, meet_code, BOT_DISPLAY_NAME)
       if not join_result.admitted:
           repo.mark_status(meet_code, 'failed', error=join_result.error)
           return
       recorder = AudioRecorder()
       audio_path = recorder.start(meet_code)
       repo.mark_status(meet_code, 'recording')
       monitor = MeetMonitor(session.page, max_duration=4*3600)
       exit_reason, participants = await monitor.run_until_exit()
       final_path = recorder.stop()
       await session.close()
       result = MeetingResult(meet_code, final_path, duration, exit_reason, participants)
       repo.mark_status(meet_code, 'processing', audio_path=final_path)
       await handoff_to_gemini(result)
   ```
7. Error paths: any exception → still try to stop recorder + close browser + log
8. Add screenshot on failure: `await page.screenshot(path=f'/data/debug/{meet_code}-fail.png')`
9. Health-check fixture: separate test Meet room (created by user) to validate join flow

## Success Criteria

- [ ] Bot successfully joins test Meet room với host admitting
- [ ] Display name appears as "Meeting Note-taker (bot)" in participant list
- [ ] Mic + cam confirmed off (host POV)
- [ ] Denied scenario: timeout returns `DENIED` status, no crash
- [ ] Risk-queue denial returns `RISK_QUEUE_DENIED` with diagnostic screenshot
- [ ] Network blip mid-join → retry logic recovers OR fails gracefully
- [ ] Bot exits cleanly when host ends meeting, bot is kicked, bot is alone for 2+ min, or hard cap triggers
- [ ] Audio file always finalized and handed off, including partial recording
- [ ] SQLite transitions correct: scheduled → joining → recording → processing

## Risk Assessment

- **Selector breakage (High):** Google updates Meet UI 2-3x/year. Mitigation: aria-label-based selectors more stable than CSS classes; centralized in `meet_selectors.py`; daily health check
- **Risk-queue denial (High):** Google may classify automated joins as suspicious. Mitigation: stealth settings from Phase 3, explicit `risk_queue_denied` branch, and Vexa/Recall fallback path if admission rate is unacceptable
- **Pre-join screen variations:** Workspace vs personal account, "Ask to join" vs direct join. Mitigation: race wait + fallback selectors
- **Auto-admission for your-domain.com domain:** if bot pre-added as attendee → skips "Ask to join" → JoinResult might miss state. Test both paths
- **Concurrent meeting attempt:** if scheduler triggers 2 jobs in overlap window → second fails (browser context busy). Phase 2 should queue; verify here
- **Browser crash mid-meeting:** recorder may keep running. Track FFmpeg PID and stop it during cleanup; process partial audio if playable
