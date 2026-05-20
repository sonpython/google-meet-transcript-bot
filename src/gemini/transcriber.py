import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from src.gemini.audio_chunker import AudioChunker

PROMPT_PATH = Path(__file__).parent / "prompts" / "transcribe_vn_v1.md"


class Transcriber:
    def __init__(self, client, chunker: AudioChunker | None = None, work_dir: Path | None = None) -> None:
        self.client = client
        self.chunker = chunker or AudioChunker()
        self.work_dir = work_dir or Path("/tmp/meeting-assistant-gemini")

    async def transcribe(self, audio_path: Path, participants: tuple[str, ...], title: str) -> str:
        prompt = _build_prompt(participants, title)
        chunk_dir = self.work_dir / _slug(audio_path.stem)
        chunks = await self.chunker.chunk(audio_path, chunk_dir)
        transcript_parts: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            chunk_prompt = (
                f"{prompt}\n\n"
                f"Chunk {index}/{len(chunks)} starts at +{chunk.offset_seconds} seconds. "
                "Use this offset as the reliable time anchor. Do not invent absolute timestamps."
            )
            text = await _retry_chunk(
                lambda chunk_path=chunk.path, prompt_text=chunk_prompt: self._transcribe_chunk(
                    chunk_path,
                    prompt_text,
                    index,
                ),
                index,
            )
            transcript_parts.append(f"## Chunk {index} (+{chunk.offset_seconds}s)\n\n{text.strip()}")
        return "\n\n".join(transcript_parts).strip()

    async def _transcribe_chunk(self, audio_path: Path, prompt: str, index: int) -> str:
        text = await self.client.generate_from_audio(audio_path, prompt)
        if has_hallucination_loop(text):
            text = await self.client.generate_from_audio(
                audio_path,
                prompt + "\n\nRetry with concise, non-repetitive transcript only.",
            )
        if has_hallucination_loop(text):
            raise RuntimeError(f"Gemini transcription loop detected in chunk {index}")
        return text


async def _retry_chunk(operation: Callable[[], Awaitable[str]], index: int) -> str:
    delays = (60, 180, 300)
    last_error: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            return await operation()
        except Exception as exc:
            last_error = exc
            if attempt < len(delays):
                await asyncio.sleep(delays[attempt])
    return (
        f"[CHUNK_TRANSCRIBE_FAILED] Chunk {index} failed after {len(delays) + 1} attempts. "
        f"Error: {last_error}"
    )


def _build_prompt(participants: tuple[str, ...], title: str) -> str:
    prompt = PROMPT_PATH.read_text()
    prompt = prompt.replace("{participant_names}", ", ".join(participants) or "Không rõ")
    return prompt.replace("{meeting_title}", title or "Không rõ")


def has_hallucination_loop(text: str, max_consecutive: int = 30) -> bool:
    previous = None
    count = 0
    for line in text.splitlines():
        normalized = " ".join(line.strip().lower().split())
        if not normalized:
            continue
        if normalized == previous:
            count += 1
        else:
            previous = normalized
            count = 1
        if count > max_consecutive:
            return True
    return False


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)[:80] or "audio"
