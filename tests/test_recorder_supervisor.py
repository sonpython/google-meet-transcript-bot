import asyncio
from pathlib import Path

import pytest

from src.bot.recorder_supervisor import RecorderSupervisor


class FakeRecorder:
    instances = []

    def __init__(self, audio_dir: Path, audio_source: str) -> None:
        self.audio_dir = audio_dir
        self.audio_source = audio_source
        self.output_path = None
        self.running = True
        FakeRecorder.instances.append(self)

    def start(self, meet_code: str, audio_source: str | None = None) -> Path:
        index = len(FakeRecorder.instances)
        self.output_path = self.audio_dir / f"{meet_code}-{index}.opus"
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"opus")
        self.source = audio_source
        return self.output_path

    def stop(self) -> Path:
        self.running = False
        return self.output_path

    def is_running(self) -> bool:
        return self.running

    def error_tail(self) -> str:
        return ""


@pytest.mark.anyio
async def test_supervisor_restarts_recorder_without_leaving_meeting(tmp_path, monkeypatch) -> None:
    FakeRecorder.instances = []
    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", FakeRecorder)

    supervisor = RecorderSupervisor(tmp_path, "default.monitor", "abc-defg-hij", "session.monitor", check_seconds=0)
    first_path = supervisor.start()
    FakeRecorder.instances[0].running = False

    for _ in range(3):
        if len(FakeRecorder.instances) > 1:
            break
        await asyncio.sleep(0)

    await supervisor.stop()

    assert first_path.name == "abc-defg-hij-1.opus"
    assert [item.source for item in FakeRecorder.instances] == ["session.monitor", "session.monitor"]
    assert [path.name for path in supervisor.paths] == ["abc-defg-hij-1.opus", "abc-defg-hij-2.opus"]


@pytest.mark.anyio
async def test_supervisor_restarts_after_bad_segment_stop(tmp_path, monkeypatch) -> None:
    class BadFirstRecorder(FakeRecorder):
        def stop(self) -> Path:
            if len(FakeRecorder.instances) == 1:
                self.running = False
                raise RuntimeError("empty audio")
            return super().stop()

    FakeRecorder.instances = []
    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", BadFirstRecorder)

    supervisor = RecorderSupervisor(tmp_path, "default.monitor", "abc-defg-hij", "session.monitor", check_seconds=0)
    supervisor.start()
    FakeRecorder.instances[0].running = False

    for _ in range(3):
        if len(FakeRecorder.instances) > 1:
            break
        await asyncio.sleep(0)

    await supervisor.stop()

    assert len(FakeRecorder.instances) == 2
    assert [path.name for path in supervisor.paths] == ["abc-defg-hij-2.opus"]
