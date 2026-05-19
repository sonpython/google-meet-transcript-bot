# Red-Team Report — Meeting Transcript Pipeline

## Summary

Claude Code red-teamed the initial 10-phase Playwright bot plan and found several issues that should be reflected before implementation starts.

The resulting plan keeps the self-built Playwright direction, but adds fallback paths and reduces unnecessary complexity.

## Findings

| Severity | Finding | Plan Response |
|---|---|---|
| P0 | Google Meet risk-queue may classify automated joins as suspicious. | Add `risk_queue_denied` branch, diagnostic screenshots, stealth mitigations, and Vexa/Recall fallback paths. |
| P0 | Vexa exists as an open-source/self-hostable meeting bot option. | Keep as Path B if Playwright admission is unreliable. |
| P1 | Recall.ai pricing was lower than initially assumed. | Treat Recall as Path C fallback, not as an impossible-cost option. |
| P1 | Gemini Vietnamese transcription quality is unverified. | Keep pilot validation and fallback to Whisper/Vietnamese STT if quality fails. |
| P1 | PipeWire is a better 2026 container audio default than PulseAudio. | Replace PulseAudio with PipeWire plus `pipewire-pulse` compatibility. |
| P2 | Playwright stealth plan was too shallow. | Add user-agent, viewport, webdriver init script, timing jitter, and explicit diagnostics. |
| P2 | Daily fixed-time health check creates repetitive bot signature. | Randomize daily health check in a 05:00-09:00 window. |
| P3 | Separate transcript and summary files add Telegram noise. | Deliver one combined meeting notes file. |
| P3 | Separate job store, `/health`, external age dependency, and standalone audio chunker are extra surface area. | Use SQLite as scheduler source of truth, remove `/health`, use Fernet, fold chunking into transcriber. |

## Applied Change Sets

- C2: PipeWire replaces PulseAudio.
- C3: 2026-level Playwright stealth notes added.
- C4: Risk-queue denial branch added.
- C5: Health check randomized.
- C6: Telegram sends one combined notes file.
- C7: Cost claims corrected and fallback paths documented.
- C8: YAGNI cuts applied.
- C9: Phase 4 absorbs bot exit detection and audio handoff; later phases renumbered.

## Open Questions

- Does the target Workspace admit the bot reliably when it is invited as an internal attendee?
- Is Gemini quality acceptable for real Vietnamese meetings with domain-specific names?
- Is Proxmox LXC audio stable enough, or should production run in a VM?
