# App Journey Story

This file is a placeholder for the product and user journey.

## Intended Journey

1. User keeps meetings on Google Calendar.
2. Bot detects qualifying Google Meet events.
3. Bot joins visibly as `Meeting Note-taker (bot)`.
4. Bot records meeting audio.
5. Gemini generates Vietnamese transcript and structured summary.
6. Telegram receives a short inline TL;DR and one combined `.md` notes file.

## Open Product Questions

- How many overlapping meetings happen in a typical week?
- Should the bot ever skip sensitive calendar titles?
- Is Telegram the long-term source of truth, or should archive/search be added later?
