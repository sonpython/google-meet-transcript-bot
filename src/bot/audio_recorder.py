import subprocess
import time
from pathlib import Path


class AudioRecorder:
    def __init__(self, audio_dir: Path, audio_source: str = "meet_capture.monitor", ffmpeg_bin: str = "ffmpeg") -> None:
        self.audio_dir = audio_dir
        self.audio_source = audio_source
        self.ffmpeg_bin = ffmpeg_bin
        self.process: subprocess.Popen | None = None
        self.output_path: Path | None = None

    def start(self, meet_code: str) -> Path:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.output_path = self.audio_dir / f"{meet_code}.opus"
        self.process = subprocess.Popen(
            [
                self.ffmpeg_bin,
                "-y",
                "-f",
                "pulse",
                "-i",
                self.audio_source,
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
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1)
        if self.process.poll() is not None:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"ffmpeg audio source failed: {self.audio_source}: {stderr.strip()}")
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
        if not self.output_path.exists() or self.output_path.stat().st_size == 0:
            raise RuntimeError(f"Recorder did not produce audio file: {self.output_path}")
        return self.output_path

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)
