---
phase: 7
title: "Telegram Delivery + Formatting"
status: implemented
priority: P1
effort: "0.5d"
dependencies: [6]
---

# Phase 7: Telegram Delivery + Formatting

## Overview

Deliver final transcript + summary to Telegram group. Inline message với TL;DR + metadata, attach one combined `.md` file. Handle Telegram size limits gracefully.

## Requirements

**Functional:**
- Inline message format:
  ```
  📋 <Meeting title>
  🕐 <date> <start>-<end> (<duration>)
  👥 <participant count>: <names>
  📝 Exit: <admitted|kicked|ended|alone>

  ## TL;DR
  <2-3 sentences>

  📎 Full notes attached below
  ```
- Attach `meeting-notes-<YYYYMMDD-HHMM>-<slug>.md`, combining summary first and transcript second
- chat_id + bot token from env
- Failure → retry 3x với exponential backoff → if still fail, log + mark `delivery_failed`

**Non-functional:**
- Telegram MarkdownV2 escaping handled correctly (special chars)
- Inline message size ≤4096 chars (truncate TL;DR if needed)
- File attachments ≤50MB (Telegram bot API limit — transcripts well under this)

## Architecture

```
src/
├── telegram_sender/
│   ├── client.py                    # python-telegram-bot wrapper
│   ├── formatter.py                 # build inline message + escape MarkdownV2
│   └── delivery.py                  # send + retry orchestration
```

## Related Code Files

**Create:**
- `src/telegram_sender/__init__.py`
- `src/telegram_sender/client.py`
- `src/telegram_sender/formatter.py`
- `src/telegram_sender/delivery.py`

**Modify:**
- `src/bot/meeting_session.py` (call delivery after gemini stage)
- `src/state/meetings_repo.py` (delivered_at timestamp)
- `pyproject.toml` (add `python-telegram-bot`)
- `.env.example` (add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)

## Implementation Steps

1. `uv add python-telegram-bot`
2. `client.py`:
   - `class TelegramClient`:
     - `async send_text(chat_id, text, parse_mode='MarkdownV2')`
     - `async send_document(chat_id, file_path, caption=None)`
3. `formatter.py`:
   - `escape_markdownv2(text) -> str` (escape `_ * [ ] ( ) ~ \` > # + - = | { } . !`)
   - `build_inline(meeting_result, tldr) -> str`:
     ```python
     return f"📋 {title}\n🕐 {dt}\n👥 {participants}\n📝 Exit: {reason}\n\n{tldr}\n\n📎 Files attached"
     ```
   - Truncate tldr at 800 chars (room for header)
4. `delivery.py`:
   - `async deliver(meeting_result, transcript_md, summary_md) -> DeliveryResult`:
     - Extract TL;DR section from summary
     - Build combined notes file
     - Build inline message
     - Send inline → success?
     - Send combined notes file → success?
     - Mark `delivered` in DB
   - Retry decorator (3 attempts)
5. Wire `meeting_session.py`:
   ```python
   await delivery.deliver(meeting_result, transcript_md, summary_md)
   repo.mark_status(meet_code, 'delivered')
   # cleanup local audio file
   if AUTO_PURGE_AUDIO:
       os.remove(audio_path)
   ```
6. Test fixture: send a fake meeting to test group, verify formatting

## Success Criteria

- [ ] Inline message renders correctly in Telegram (no escape glitches)
- [ ] Combined `.md` file attaches, downloads, and opens correctly
- [ ] TL;DR extracted cleanly from summary
- [ ] Long meeting title (>200 chars) truncates gracefully
- [ ] Telegram rate limit (30 msg/sec) handled (we send 2 messages per meeting, easily under)
- [ ] Network blip during send → retry recovers
- [ ] Final state: `meetings.status = 'delivered'` with timestamp

## Risk Assessment

- MarkdownV2 escape bugs: edge case chars in meeting titles. Use proven escape function, test với titles containing `()`, `.`, `_`, `*`
- Telegram bot blocked from group → 403 error. Document recovery (re-add bot)
- File size: extremely long meetings could exceed 50MB attachment limit. 4h transcript ~ 200KB plaintext. Safe
- Bot token in env: ensure not committed. `.gitignore` `.env`
