from pathlib import Path
from datetime import UTC, datetime

from src.gemini.summarizer import Summarizer
from src.gemini.transcriber import Transcriber
from src.models.meeting_result import MeetingResult


class GeminiPipeline:
    def __init__(self, client, output_dir: Path) -> None:
        self.transcriber = Transcriber(client, work_dir=output_dir / ".chunks")
        self.summarizer = Summarizer(client)
        self.output_dir = output_dir

    async def process(self, result: MeetingResult) -> tuple[Path, Path, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        transcript = await self.transcriber.transcribe(
            result.audio_path,
            result.participant_names,
            result.title,
        )
        summary = await self.summarizer.summarize(transcript, result.title)
        slug = _slug(result.title or result.meet_code)
        transcript_path = self.output_dir / f"transcript-{slug}.md"
        summary_path = self.output_dir / f"summary-{slug}.md"
        notes_path = self.output_dir / f"meeting-notes-{slug}.md"
        marker = _segment_marker(result)
        _append_segment(transcript_path, marker, transcript)
        _append_segment(summary_path, marker, summary)
        _append_segment(
            notes_path,
            marker,
            f"## Summary\n\n{summary}\n\n## Transcript\n\n{transcript}",
            header=f"# {result.title or result.meet_code}",
        )
        return transcript_path, summary_path, notes_path


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)[:80] or "meeting"


def _segment_marker(result: MeetingResult) -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"## Segment {timestamp}\n\n"
        f"- Meet code: {result.meet_code}\n"
        f"- Duration: {result.duration_sec}s\n"
        f"- Exit reason: {result.exit_reason}\n"
    )


def _append_segment(path: Path, marker: str, content: str, header: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if not path.exists() and header:
        prefix = f"{header}\n\n"
    separator = "\n\n---\n\n" if path.exists() and path.stat().st_size else ""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{separator}{prefix}{marker}\n{content.strip()}\n")
