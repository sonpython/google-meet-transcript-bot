import asyncio
from pathlib import Path

import pytest

from src.gemini.audio_chunker import AudioChunk
from src.gemini.pipeline import GeminiPipeline
from src.gemini.transcriber import Transcriber, has_hallucination_loop
from src.models.meeting_result import MeetingResult


class FakeChunker:
    async def chunk(self, audio_path: Path, output_dir: Path) -> list[AudioChunk]:
        first = output_dir / "chunk-000.mp3"
        second = output_dir / "chunk-001.mp3"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(b"a")
        second.write_bytes(b"b")
        return [AudioChunk(first, 0), AudioChunk(second, 840)]


class FakeGeminiClient:
    def __init__(self) -> None:
        self.audio_calls: list[tuple[Path, str]] = []
        self.text_calls: list[str] = []

    async def generate_from_audio(self, audio_path: Path, prompt: str) -> str:
        self.audio_calls.append((audio_path, prompt))
        return f"Transcript for {audio_path.name}"

    async def generate_text(self, prompt: str) -> str:
        self.text_calls.append(prompt)
        if "Meeting Minutes" in prompt:
            return "## Thông Tin Cuộc Họp\nMinutes content"
        return "## TL;DR\nSummary content"


def test_hallucination_loop_detection() -> None:
    assert has_hallucination_loop("\n".join(["vâng"] * 31))
    assert not has_hallucination_loop("vâng\nừm\nvâng")


def test_transcriber_chunks_audio_with_offsets(tmp_path: Path) -> None:
    client = FakeGeminiClient()
    transcriber = Transcriber(client, chunker=FakeChunker(), work_dir=tmp_path / "chunks")

    transcript = asyncio.run(transcriber.transcribe(tmp_path / "meeting.opus", ("An",), "Weekly Sync"))

    assert "## Chunk 1 (+0s)" in transcript
    assert "## Chunk 2 (+840s)" in transcript
    assert len(client.audio_calls) == 2
    assert "Weekly Sync" in client.audio_calls[0][1]
    assert "+840 seconds" in client.audio_calls[1][1]


def test_transcriber_raises_after_repeated_loop(tmp_path: Path) -> None:
    class LoopClient(FakeGeminiClient):
        async def generate_from_audio(self, audio_path: Path, prompt: str) -> str:
            return "\n".join(["đó"] * 31)

    transcriber = Transcriber(LoopClient(), chunker=FakeChunker(), work_dir=tmp_path / "chunks")

    with pytest.raises(RuntimeError, match="loop detected"):
        asyncio.run(transcriber.transcribe(tmp_path / "meeting.opus", (), ""))


def test_pipeline_writes_outputs(tmp_path: Path) -> None:
    client = FakeGeminiClient()
    pipeline = GeminiPipeline(client, tmp_path / "out")
    pipeline.transcriber = Transcriber(client, chunker=FakeChunker(), work_dir=tmp_path / "chunks")
    result = MeetingResult(
        meet_code="abc-defg-hij",
        audio_path=tmp_path / "meeting.opus",
        duration_sec=120,
        exit_reason="empty_meeting",
        participant_names=("An",),
        title="Weekly Sync",
    )

    transcript_path, summary_path, minutes_path, notes_path = asyncio.run(pipeline.process(result))

    assert transcript_path.exists()
    assert "## Segment " in summary_path.read_text()
    assert "## TL;DR\nSummary content" in summary_path.read_text()
    assert "## Thông Tin Cuộc Họp\nMinutes content" in minutes_path.read_text()
    assert len(client.text_calls) == 2
    assert "# Weekly Sync" in notes_path.read_text()
    assert "## Meeting Minutes" in notes_path.read_text()
    assert "- Meet code: abc-defg-hij" in notes_path.read_text()
