import asyncio
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.bot.audio_recorder import AudioRecorder


class RecorderSupervisor:
    def __init__(
        self,
        audio_dir: Path,
        default_source: str,
        meet_code: str,
        audio_source: str,
        check_seconds: int = 5,
    ) -> None:
        self.audio_dir = audio_dir
        self.default_source = default_source
        self.meet_code = meet_code
        self.audio_source = audio_source
        self.check_seconds = check_seconds
        self.paths: list[Path] = []
        self.durations: list[int] = []
        self._recorder: AudioRecorder | None = None
        self._started_at: datetime | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.log = structlog.get_logger(__name__)

    def start(self) -> Path:
        path = self._start_segment()
        self._task = asyncio.create_task(self._watch())
        return path

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._finish_current_segment()

    def is_running(self) -> bool:
        return bool(self._recorder and self._recorder.is_running())

    async def _watch(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.check_seconds)
            if self._stopping or self.is_running():
                continue
            tail = self._recorder.error_tail().strip() if self._recorder else ""
            self.log.error(
                "recorder_supervisor_segment_stopped",
                meet_code=self.meet_code,
                ffmpeg_error=tail[-500:],
            )
            self._finish_current_segment()
            self._start_segment()

    def _start_segment(self) -> Path:
        self._recorder = AudioRecorder(self.audio_dir, self.default_source)
        self._started_at = datetime.now(UTC)
        path = self._recorder.start(self.meet_code, audio_source=self.audio_source)
        self.log.info("recorder_supervisor_segment_started", meet_code=self.meet_code, audio_path=str(path))
        return path

    def _finish_current_segment(self) -> bool:
        if not self._recorder:
            return False
        try:
            try:
                path = self._recorder.stop()
            except Exception as exc:
                self.log.exception("recorder_supervisor_segment_discarded", meet_code=self.meet_code, error=str(exc))
                return False
            else:
                duration = self._segment_duration()
                if path not in self.paths:
                    self.paths.append(path)
                    self.durations.append(duration)
                self.log.info(
                    "recorder_supervisor_segment_finished",
                    meet_code=self.meet_code,
                    audio_path=str(path),
                    duration_sec=duration,
                )
                return True
        finally:
            self._recorder = None
            self._started_at = None

    def _segment_duration(self) -> int:
        if not self._started_at:
            return 0
        return max(0, int((datetime.now(UTC) - self._started_at).total_seconds()))
