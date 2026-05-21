from pathlib import Path

from src.duration_format import format_duration
from src.models.meeting_result import MeetingResult

SPECIAL = r"_*[]()~`>#+-=|{}.!"


def escape_markdownv2(text: str) -> str:
    return "".join(f"\\{ch}" if ch in SPECIAL else ch for ch in text)


def extract_tldr(summary: str) -> str:
    marker = "## TL;DR"
    if marker not in summary:
        return summary.strip()[:800]
    body = summary.split(marker, 1)[1]
    next_section = body.find("\n## ")
    tldr = body[:next_section] if next_section != -1 else body
    return tldr.strip()[:800]


def build_inline(result: MeetingResult, summary: str) -> str:
    participants = ", ".join(result.participant_names) or "Không rõ"
    text = (
        f"📋 {result.title or result.meet_code}\n"
        f"⏱ Duration: {format_duration(result.duration_sec)}\n"
        f"👥 {len(result.participant_names)}: {participants}\n"
        f"## TL;DR\n{extract_tldr(summary)}\n\n"
        "📎 Full notes attached"
    )
    return escape_markdownv2(text[:4000])


def build_notes_file(path: Path, title: str, summary: str, transcript: str) -> Path:
    path.write_text(f"# {title}\n\n{summary}\n\n## Transcript\n\n{transcript}")
    return path
