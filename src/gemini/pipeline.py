from pathlib import Path
from datetime import UTC, datetime
from typing import Awaitable, Callable

from src.gemini.summarizer import Summarizer
from src.gemini.transcriber import Transcriber
from src.duration_format import format_duration
from src.models.meeting_result import MeetingResult


class GeminiPipeline:
    def __init__(self, client, output_dir: Path) -> None:
        self.transcriber = Transcriber(client, work_dir=output_dir / ".chunks")
        self.summarizer = Summarizer(client)
        self.output_dir = output_dir

    async def process(self, result: MeetingResult, generate_documents: bool = False) -> tuple[Path, ...]:
        return await self.process_many((result,), generate_documents=generate_documents)

    async def process_many(
        self,
        results: tuple[MeetingResult, ...] | list[MeetingResult],
        append: bool = True,
        on_progress: Callable[[str, int, int], Awaitable[None] | None] | None = None,
        generate_documents: bool = False,
    ) -> tuple[Path, ...]:
        if not results:
            raise ValueError("results must not be empty")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        first = results[0]
        transcript_path, combined_transcript = await self._write_transcript(results, append, on_progress)
        if not generate_documents:
            await _notify(on_progress, "done", len(results), len(results))
            return (transcript_path,)
        summary_path, minutes_path, notes_path = await self.generate_documents(
            combined_transcript,
            first.title,
            first.meet_code,
            first.admin_instruction,
            append=append,
            on_progress=on_progress,
        )
        return transcript_path, summary_path, minutes_path, notes_path

    async def _write_transcript(
        self,
        results: tuple[MeetingResult, ...] | list[MeetingResult],
        append: bool,
        on_progress: Callable[[str, int, int], Awaitable[None] | None] | None,
    ) -> tuple[Path, str]:
        first = results[0]
        transcript_parts = []
        total = len(results)
        for index, result in enumerate(results, start=1):
            await _notify(on_progress, "transcribing", index, total)
            transcript = await self.transcriber.transcribe(
                result.audio_path,
                result.participant_names,
                result.title,
                result.admin_instruction,
            )
            transcript_parts.append(f"{_segment_marker(result)}\n{transcript}")
        combined_transcript = "\n\n---\n\n".join(transcript_parts).strip()
        slug = _slug(first.title or first.meet_code)
        transcript_path = self.output_dir / f"transcript-{slug}.md"
        marker = _aggregate_marker(results)
        _write_segment(transcript_path, marker, combined_transcript, append=append)
        await _notify(on_progress, "writing_transcript", total, total)
        return transcript_path, combined_transcript

    async def generate_documents(
        self,
        transcript: str,
        title: str,
        meet_code: str,
        admin_instruction: str,
        append: bool = False,
        on_progress: Callable[[str, int, int], Awaitable[None] | None] | None = None,
    ) -> tuple[Path, Path, Path]:
        if not admin_instruction.strip():
            raise ValueError("admin_instruction is required to generate meeting minutes")
        total = 3
        await _notify(on_progress, "summarizing", 1, total)
        summary = await self.summarizer.summarize(transcript, title, admin_instruction)
        await _notify(on_progress, "minutes", 2, total)
        minutes = await self.summarizer.minutes(transcript, title, admin_instruction)
        slug = _slug(title or meet_code)
        summary_path = self.output_dir / f"summary-{slug}.md"
        minutes_path = self.output_dir / f"meeting-minutes-{slug}.md"
        notes_path = self.output_dir / f"meeting-notes-{slug}.md"
        marker = _document_marker(meet_code)
        _write_segment(summary_path, marker, summary, append=append)
        _write_segment(minutes_path, marker, minutes, header=f"# Meeting Minutes - {title or meet_code}", append=append)
        _write_segment(
            notes_path,
            marker,
            f"## Summary\n\n{summary}\n\n## Meeting Minutes\n\n{minutes}\n\n## Transcript\n\n{transcript}",
            header=f"# {title or meet_code}",
            append=append,
        )
        await _notify(on_progress, "writing", 3, total)
        return summary_path, minutes_path, notes_path


async def _notify(
    on_progress: Callable[[str, int, int], Awaitable[None] | None] | None,
    stage: str,
    batch: int,
    total: int,
) -> None:
    if not on_progress:
        return
    result = on_progress(stage, batch, total)
    if result is not None:
        await result


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


def _document_marker(meet_code: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"## Generated {timestamp}\n\n- Meet code: {meet_code}\n"


def _write_segment(path: Path, marker: str, content: str, header: str | None = None, append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if (not append or not path.exists()) and header:
        prefix = f"{header}\n\n"
    separator = "\n\n---\n\n" if append and path.exists() and path.stat().st_size else ""
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(f"{separator}{prefix}{marker}\n{content.strip()}\n")
