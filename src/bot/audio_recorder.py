import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


class AudioRecorder:
    def __init__(self, audio_dir: Path, audio_source: str = "meet_capture.monitor", ffmpeg_bin: str = "ffmpeg") -> None:
        self.audio_dir = audio_dir
        self.audio_source = audio_source
        self.ffmpeg_bin = ffmpeg_bin
        self.process: subprocess.Popen | None = None
        self.output_path: Path | None = None
        self.stderr_path: Path | None = None
        self._stderr_handle = None

    def start(self, meet_code: str, audio_source: str | None = None) -> Path:
        source = audio_source or self.audio_source
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.output_path = self._next_output_path(meet_code)
        self.stderr_path = self.output_path.with_suffix(".ffmpeg.log")
        self._stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                self.ffmpeg_bin,
                "-y",
                "-nostats",
                "-loglevel",
                "error",
                "-f",
                "pulse",
                "-i",
                source,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                str(self.output_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_handle,
            text=True,
        )
        time.sleep(1)
        if self.process.poll() is not None:
            stderr = self._read_stderr_tail()
            self._close_stderr()
            raise RuntimeError(f"ffmpeg audio source failed: {source}: {stderr.strip()}")
        return self.output_path

    def stop(self) -> Path:
        if not self.output_path:
            raise RuntimeError("Recorder was not started")
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self._close_stderr()
        if not self.output_path.exists() or self.output_path.stat().st_size == 0:
            raise RuntimeError(f"Recorder did not produce audio file: {self.output_path}")
        return self.output_path

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def error_tail(self) -> str:
        return self._read_stderr_tail()

    def _next_output_path(self, meet_code: str) -> Path:
        base_path = self.audio_dir / f"{meet_code}.opus"
        if not base_path.exists():
            return base_path
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return self.audio_dir / f"{meet_code}-{stamp}.opus"

    def _close_stderr(self) -> None:
        if self._stderr_handle and not self._stderr_handle.closed:
            self._stderr_handle.close()

    def _read_stderr_tail(self) -> str:
        if self._stderr_handle and not self._stderr_handle.closed:
            self._stderr_handle.flush()
        if not self.stderr_path or not self.stderr_path.exists():
            return ""
        text = self.stderr_path.read_text(encoding="utf-8", errors="replace")
        return text[-2000:]
