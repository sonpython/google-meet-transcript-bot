---
phase: 9
title: "Pilot + Tuning"
status: pending_live_credentials
priority: P1
effort: "1-2d"
dependencies: [8]
---

# Phase 9: Pilot + Tuning

## Overview

Run pipeline against 5-10 real meetings, measure quality metrics, tune Gemini prompts and bot behavior. Validate success criteria. Document operations runbook.

## Requirements

**Functional:**
- Deploy to Proxmox LXC production
- Run 5-10 real meetings (mix host/attend, mix lengths)
- Manual review each: transcript accuracy, speaker diarization, summary correctness
- Tune prompts based on feedback (v1 → v2 if needed)
- Document operations runbook (start/stop, refresh login, debug failures)

**Non-functional:**
- Success metric validation:
  - Coverage ≥95%
  - Bot admission measured; ≥95% target, but risk-queue failures trigger Path B/C review
  - Latency p50 ≤8 min, p95 ≤15 min
  - Transcript accuracy ≥90% on key decisions/names
  - Cost ≤$15/month projection
- Decision: ship to daily use OR identify show-stopper issues

## Architecture

No new code components. Configuration tuning + observability:

```
docs/
├── runbook.md                       # operations guide
├── pilot-report.md                  # measured metrics + findings
└── prompt-tuning-log.md             # prompt v1 → v2 changes + rationale
```

## Related Code Files

**Create:**
- `docs/runbook.md`
- `plans/reports/pilot-260519-tuning-report.md` (auto-update with each pilot meeting)
- Potentially: `src/gemini/prompts/transcribe_vn_v2.md`, `summarize_vn_v2.md` (if tuning needed)

**Modify (only if tuning required):**
- Prompts files
- `meet_selectors.py` (if selectors needed updating)
- `gemini/transcriber.py` (chunk size if quality issue at boundaries)

## Implementation Steps

1. **Pre-pilot checklist:**
   - All previous phases tested individually
   - Production LXC provisioned, systemd running
   - Telegram group has bot, chat_id verified
   - Test meeting completed end-to-end successfully
2. **Pilot run (5-10 meetings):**
   - Don't filter — let pipeline process all calendar Meet events for user@your-domain.com
   - Capture for each meeting:
     - Meeting type (host/attend), duration, participants
     - Bot admission outcome
     - Latency: meeting end → Telegram delivery
     - Gemini cost (tokens × pricing)
     - Manual quality score (1-5) for transcript + summary
3. **Quality review per meeting:**
   - Re-listen to recording, compare against transcript
   - Score:
     - Word accuracy (VN spelling, names)
     - Speaker diarization accuracy
     - Decision/action capture in summary
   - Note any patterns (specific accents miss-transcribed, technical terms wrong, etc.)
4. **Tune based on findings:**
   - Prompt v2 if quality patterns identified (e.g. add domain-specific instructions)
   - Chunk overlap if boundary issues
   - Selectors update if bot UI quirks hit
   - Add custom names dictionary if frequently-mentioned people get mis-spelled
5. **Stress test scenarios:**
   - Concurrent meeting (2 events overlap) → verify queue behavior
   - Very short meeting (3 min) → verify processing
   - Long meeting (2h+) → verify chunking
   - Bot kicked early → verify partial transcript still delivered
6. **Document runbook:**
   - How to refresh bot login (storageState expired)
   - How to inspect SQLite state
   - How to re-process a meeting manually
   - How to update prompts and roll back
   - Common failure patterns and fixes
7. **Final report:**
   - Metrics table (target vs actual)
   - Gemini cost projection at 30h/mo
   - Go / no-go decision
   - Known issues + post-MVP backlog

## Success Criteria

- [ ] 5+ real meetings processed end-to-end
- [ ] Manual review confirms ≥90% accuracy on key info
- [ ] All success metrics from brainstorm Section 6 measured and reported
- [ ] Runbook complete enough for non-author to operate the system
- [ ] Pilot report committed to `plans/reports/`
- [ ] Go/no-go decision made — if NO, list specific blockers
- [ ] Known issues logged as post-MVP backlog items

## Risk Assessment

- Real meetings have private content → ensure storage + Telegram delivery private; review pilot data sensitively
- Gemini Vietnamese quality could be lower than expected → fallback: Whisper large-v3 self-hosted plan; estimate dev time if needed
- Bot detection by Google: if account flagged during pilot → operational, not technical risk; have manual fallback (record screen on local Mac)
- Discovery of show-stopper issue (e.g. PipeWire doesn't work reliably in LXC or risk-queue blocks joins) → escalate to Vexa/Recall fallback path or VM deployment
