from pathlib import Path

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
        transcript_path.write_text(transcript)
        summary_path.write_text(summary)
        notes_path.write_text(f"# {result.title or result.meet_code}\n\n{summary}\n\n## Transcript\n\n{transcript}")
        return transcript_path, summary_path, notes_path


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)[:80] or "meeting"
