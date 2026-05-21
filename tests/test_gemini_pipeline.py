import asyncio
from pathlib import Path

from src.gemini.audio_chunker import AudioChunk
from src.gemini.pipeline import GeminiPipeline
from src.gemini.summarizer import sanitize_minutes
from src.gemini import transcriber as transcriber_module
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
        if "## Thông Tin Cuộc Họp" in prompt:
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


def test_transcriber_marks_failed_chunk_after_repeated_loop(tmp_path: Path, monkeypatch) -> None:
    class LoopClient(FakeGeminiClient):
        async def generate_from_audio(self, audio_path: Path, prompt: str) -> str:
            return "\n".join(["đó"] * 31)

    async def no_sleep(_delay: int) -> None:
        return None

    monkeypatch.setattr(transcriber_module.asyncio, "sleep", no_sleep)
    transcriber = Transcriber(LoopClient(), chunker=FakeChunker(), work_dir=tmp_path / "chunks")

    transcript = asyncio.run(transcriber.transcribe(tmp_path / "meeting.opus", (), ""))

    assert "[CHUNK_TRANSCRIBE_FAILED] Chunk 1 failed after 4 attempts" in transcript
    assert "[CHUNK_TRANSCRIBE_FAILED] Chunk 2 failed after 4 attempts" in transcript


def test_pipeline_writes_transcript_by_default(tmp_path: Path) -> None:
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

    output_paths = asyncio.run(pipeline.process(result))
    transcript_path = output_paths[0]

    assert len(output_paths) == 1
    assert transcript_path.exists()
    assert "## Session " in transcript_path.read_text()
    assert len(client.text_calls) == 0


def test_pipeline_generates_documents_when_requested(tmp_path: Path) -> None:
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
        admin_instruction="Write professional minutes.",
    )

    transcript_path, summary_path, minutes_path, notes_path = asyncio.run(
        pipeline.process(result, generate_documents=True)
    )

    assert transcript_path.exists()
    assert "## Generated " in summary_path.read_text()
    assert "## TL;DR\nSummary content" in summary_path.read_text()
    assert "## Thông Tin Cuộc Họp\nMinutes content" in minutes_path.read_text()
    assert len(client.text_calls) == 2
    assert "# Weekly Sync" in notes_path.read_text()
    assert "## Meeting Minutes" in notes_path.read_text()
    assert "- Meet code: abc-defg-hij" in notes_path.read_text()
    assert "- Duration: 2m 0s" in notes_path.read_text()
    assert "Exit reason" not in notes_path.read_text()


def test_pipeline_passes_admin_instruction_to_prompts(tmp_path: Path) -> None:
    client = FakeGeminiClient()
    pipeline = GeminiPipeline(client, tmp_path / "out")
    pipeline.transcriber = Transcriber(client, chunker=FakeChunker(), work_dir=tmp_path / "chunks")
    result = MeetingResult(
        meet_code="abc-defg-hij",
        audio_path=tmp_path / "meeting.opus",
        duration_sec=120,
        exit_reason="force_out",
        participant_names=("An",),
        title="Weekly Sync",
        admin_instruction="Map Bob to Robert and focus on action items.",
    )

    asyncio.run(pipeline.process(result, generate_documents=True))

    assert "Map Bob to Robert" in client.audio_calls[0][1]
    assert all("Map Bob to Robert" in prompt for prompt in client.text_calls)


def test_pipeline_reports_progress_by_stage(tmp_path: Path) -> None:
    client = FakeGeminiClient()
    pipeline = GeminiPipeline(client, tmp_path / "out")
    pipeline.transcriber = Transcriber(client, chunker=FakeChunker(), work_dir=tmp_path / "chunks")
    result = MeetingResult(
        meet_code="abc-defg-hij",
        audio_path=tmp_path / "meeting.opus",
        duration_sec=120,
        exit_reason="force_out",
        participant_names=("An",),
        title="Weekly Sync",
        admin_instruction="Generate clean minutes.",
    )
    progress = []

    async def on_progress(stage: str, batch: int, total: int) -> None:
        progress.append((stage, batch, total))

    asyncio.run(pipeline.process_many((result,), on_progress=on_progress, generate_documents=True))

    assert progress == [
        ("transcribing", 1, 1),
        ("writing_transcript", 1, 1),
        ("summarizing", 1, 3),
        ("minutes", 2, 3),
        ("writing", 3, 3),
    ]


def test_sanitize_minutes_removes_model_preamble() -> None:
    raw = (
        "Chắc chắn rồi, đây là biên bản cuộc họp (Meeting Minutes) từ transcript bạn đã cung cấp.\n\n"
        "## Thông Tin Cuộc Họp\n"
        "- Chủ đề: Demo\n"
    )

    cleaned = sanitize_minutes(raw)

    assert cleaned.startswith("## Thông Tin Cuộc Họp")
    assert "Chắc chắn rồi" not in cleaned
