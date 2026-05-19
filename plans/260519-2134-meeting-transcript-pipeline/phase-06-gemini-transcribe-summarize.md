---
phase: 6
title: "Gemini Transcribe + Summarize"
status: implemented_offline
priority: P1
effort: "1.5d"
dependencies: [4, 5]
---

# Phase 6: Gemini Transcribe + Summarize

## Overview

Send `.opus` audio file to Gemini 2.5 Pro multimodal API → Vietnamese transcript with speaker diarization + structured summary (TL;DR, Decisions, Action Items, Next Steps). Chunk meetings >2h.

## Requirements

**Functional:**
- Input: `MeetingResult` (audio_path, meet_code, duration, participants, title)
- Two Gemini calls (sequential):
  1. **Transcribe:** audio → Vietnamese transcript with speaker labels + ~30s timestamps
  2. **Summarize:** transcript → structured markdown (TL;DR/Decisions/Action Items/Next Steps)
- Output: 2 markdown files — `transcript-<date>-<slug>.md`, `summary-<date>-<slug>.md`
- Chunk meetings >120 min: split audio at 30 min boundaries (10s overlap), parallel transcribe, stitch
- Skip meetings <2 min duration

**Non-functional:**
- Retry với exponential backoff on Gemini rate limit / transient error (max 5 attempts)
- Token usage logged per call (cost tracking)
- Prompt versioning: `prompts/transcribe-vn-v1.md`, `prompts/summarize-vn-v1.md`

## Architecture

```
src/
├── gemini/
│   ├── client.py                    # Gemini API wrapper với retry
│   ├── transcriber.py               # audio → transcript, includes chunking helper
│   ├── summarizer.py                # transcript → summary
│   └── prompts/
│       ├── transcribe_vn_v1.md
│       └── summarize_vn_v1.md
```

## Related Code Files

**Create:**
- `src/gemini/__init__.py`
- `src/gemini/client.py`
- `src/gemini/transcriber.py`
- `src/gemini/summarizer.py`
- `src/gemini/prompts/transcribe_vn_v1.md`
- `src/gemini/prompts/summarize_vn_v1.md`

**Modify:**
- `src/bot/meeting_session.py` (call gemini pipeline after audio handoff)
- `pyproject.toml` (add `google-genai`)
- `.env.example` (add `GEMINI_API_KEY`)

## Implementation Steps

1. `uv add google-genai`
2. `client.py`:
   - Wrapper around `google.genai.Client(api_key=...)`
   - Retry decorator (5 attempts, exponential backoff 2^n seconds)
   - Cost logger: capture `usage_metadata` per response
3. `prompts/transcribe_vn_v1.md`:
   ```
   Bạn là transcriber chuyên nghiệp. Audio sau là cuộc họp tiếng Việt.
   - Transcribe toàn bộ nội dung sang văn bản tiếng Việt chính xác
   - Phân biệt speaker bằng nhãn "Speaker 1:", "Speaker 2:"... (consistent across audio)
   - Nếu participant_names được cung cấp, map speaker → name khi có thể: {participant_names}
   - Thêm timestamp [HH:MM:SS] mỗi ~30 giây hoặc khi đổi speaker
   - KHÔNG thêm bình luận, KHÔNG paraphrase, giữ nguyên ngôn ngữ gốc
   - Output thuần text, không markdown wrap
   ```
4. `prompts/summarize_vn_v1.md`:
   ```
   Bạn nhận transcript meeting tiếng Việt. Tạo summary có cấu trúc:

   ## TL;DR
   (2-3 câu tóm tắt key outcomes)

   ## Decisions
   - Quyết định 1 (ai quyết, context ngắn)
   - ...

   ## Action Items
   - [ ] <Tên người> — <Task cụ thể> — <Deadline nếu có>
   - ...

   ## Next Steps
   - Bước tiếp theo của cả nhóm
   - ...

   Quy tắc:
   - Tiếng Việt, ngắn gọn, concrete
   - Nếu không có decisions/actions/next steps → ghi "Không có"
   - KHÔNG bịa thông tin không có trong transcript
   ```
5. `transcriber.py`:
   - `async transcribe(audio_path, participants, title) -> str`:
     - If duration <= 120 min: single call
     - Else: internal helper splits with ffmpeg at 30 min boundaries (10s overlap), parallel transcribes (max 3 concurrent), then stitches
   - Upload audio via Gemini Files API (resumable for large files)
6. `summarizer.py`:
   - `async summarize(transcript, title, datetime) -> str` → returns full markdown summary
7. Wire into `meeting_session.py`:
   ```python
   transcript_md = await transcriber.transcribe(audio_path, participants, title)
   summary_md = await summarizer.summarize(transcript_md, title, start_time)
   save_to_disk(transcript_md, summary_md)
   repo.update(meet_code, transcript_path=..., summary_path=...)
   await telegram_send(transcript_md, summary_md, ...)  # Phase 7
   ```
8. Cleanup: delete `.opus` file sau khi transcribe success (configurable retention)

## Success Criteria

- [ ] 30-min test meeting → transcript VN, speaker diarization correct (≥90% accuracy on names)
- [ ] Summary follows exact structure (TL;DR/Decisions/Actions/Next Steps)
- [ ] 2h+ meeting → chunked, stitched, transcript continuous (no gaps at chunk boundaries)
- [ ] Rate limit triggered → retry succeeds, no data loss
- [ ] Cost per 1h meeting logged ≤$0.30
- [ ] Prompt files versioned and easy to A/B (just bump filename)

## Risk Assessment

- Gemini Vietnamese accuracy may vary. Pilot before locking. Fallback: Whisper large-v3 self-hosted (~$0 marginal cost but slower)
- Speaker diarization in single audio file may confuse names across chunks. Mitigation: include participant_names in prompt; map post-hoc if needed
- Large file upload via Files API: 2GB limit per file; 1h opus = ~14MB. Safe.
- Context window: 2.5 Pro = 2M tokens. 4h transcript ~ 60K tokens. Safe.
- Prompt drift: small wording changes can swing output quality. Version prompts, manual review samples
