import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioChunk:
    path: Path
    offset_seconds: int


class AudioChunker:
    def __init__(self, chunk_seconds: int = 14 * 60) -> None:
        self.chunk_seconds = chunk_seconds

    async def chunk(self, audio_path: Path, output_dir: Path) -> list[AudioChunk]:
        output_dir.mkdir(parents=True, exist_ok=True)
        pattern = output_dir / "chunk-%03d.mp3"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "segment",
            "-segment_time",
            str(self.chunk_seconds),
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
        await asyncio.to_thread(_run_ffmpeg, cmd)
        chunks = sorted(output_dir.glob("chunk-*.mp3"))
        if not chunks:
            raise RuntimeError(f"ffmpeg did not produce audio chunks for {audio_path}")
        return [AudioChunk(path=path, offset_seconds=index * self.chunk_seconds) for index, path in enumerate(chunks)]


def _run_ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)
