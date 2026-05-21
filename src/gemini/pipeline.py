from pathlib import Path
from datetime import UTC, datetime

from src.gemini.summarizer import Summarizer
from src.gemini.transcriber import Transcriber
from src.duration_format import format_duration
from src.models.meeting_result import MeetingResult


class GeminiPipeline:
    def __init__(self, client, output_dir: Path) -> None:
        self.transcriber = Transcriber(client, work_dir=output_dir / ".chunks")
        self.summarizer = Summarizer(client)
        self.output_dir = output_dir

    async def process(self, result: MeetingResult) -> tuple[Path, Path, Path, Path]:
        return await self.process_many((result,))

    async def process_many(self, results: tuple[MeetingResult, ...] | list[MeetingResult], append: bool = True) -> tuple[Path, Path, Path, Path]:
        if not results:
            raise ValueError("results must not be empty")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        first = results[0]
        transcript_parts = []
        for result in results:
            transcript = await self.transcriber.transcribe(
                result.audio_path,
                result.participant_names,
                result.title,
                result.admin_instruction,
            )
            transcript_parts.append(f"{_segment_marker(result)}\n{transcript}")
        combined_transcript = "\n\n---\n\n".join(transcript_parts).strip()
        summary = await self.summarizer.summarize(combined_transcript, first.title, first.admin_instruction)
        minutes = await self.summarizer.minutes(combined_transcript, first.title, first.admin_instruction)
        slug = _slug(first.title or first.meet_code)
        transcript_path = self.output_dir / f"transcript-{slug}.md"
        summary_path = self.output_dir / f"summary-{slug}.md"
        minutes_path = self.output_dir / f"meeting-minutes-{slug}.md"
        notes_path = self.output_dir / f"meeting-notes-{slug}.md"
        marker = _aggregate_marker(results)
        _write_segment(transcript_path, marker, combined_transcript, append=append)
        _write_segment(summary_path, marker, summary, append=append)
        _write_segment(minutes_path, marker, minutes, header=f"# Meeting Minutes - {first.title or first.meet_code}", append=append)
        _write_segment(
            notes_path,
            marker,
            f"## Summary\n\n{summary}\n\n## Meeting Minutes\n\n{minutes}\n\n## Transcript\n\n{combined_transcript}",
            header=f"# {first.title or first.meet_code}",
            append=append,
        )
        return transcript_path, summary_path, minutes_path, notes_path


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)[:80] or "meeting"


def _segment_marker(result: MeetingResult) -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"## Segment {timestamp}\n\n"
        f"- Meet code: {result.meet_code}\n"
        f"- Duration: {format_duration(result.duration_sec)}\n"
    )


def _aggregate_marker(results: tuple[MeetingResult, ...] | list[MeetingResult]) -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    first = results[0]
    total_duration = sum(result.duration_sec for result in results)
    return (
        f"## Session {timestamp}\n\n"
        f"- Meet code: {first.meet_code}\n"
        f"- Segments: {len(results)}\n"
        f"- Total duration: {format_duration(total_duration)}\n"
    )


def _write_segment(path: Path, marker: str, content: str, header: str | None = None, append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if (not append or not path.exists()) and header:
        prefix = f"{header}\n\n"
    separator = "\n\n---\n\n" if append and path.exists() and path.stat().st_size else ""
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(f"{separator}{prefix}{marker}\n{content.strip()}\n")
