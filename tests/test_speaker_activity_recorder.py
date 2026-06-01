import asyncio
import json
from pathlib import Path

import pytest

from src.bot.speaker_activity_recorder import SpeakerActivityRecorder, speaker_timeline_path


class FakePage:
    def __init__(self, snapshots: list[list[str]]) -> None:
        self.snapshots = snapshots
        self.index = 0

    async def evaluate(self, _script: str) -> list[str]:
        if self.index >= len(self.snapshots):
            return self.snapshots[-1]
        value = self.snapshots[self.index]
        self.index += 1
        return value


class FakeSleep:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _seconds: float) -> None:
        self.calls += 1
        await asyncio.sleep(0)


@pytest.mark.anyio
async def test_speaker_activity_recorder_writes_sidecar_for_segment(tmp_path: Path) -> None:
    audio_path = tmp_path / "abc-defg-hij.opus"
    audio_path.write_bytes(b"opus")
    sleep = FakeSleep()
    recorder = SpeakerActivityRecorder(
        FakePage([["Bot"], ["An"], ["An"], [], ["Binh"]]),
        "abc-defg-hij",
        ignored_names=("Bot",),
        poll_seconds=0.2,
        sleep=sleep,
    )

    recorder.start()
    recorder.start_segment(audio_path)
    while sleep.calls < 5:
        await asyncio.sleep(0)
    await recorder.stop()

    payload = json.loads(speaker_timeline_path(audio_path).read_text(encoding="utf-8"))
    speakers = [event["speaker"] for event in payload["events"]]
    assert "Bot" not in speakers
    assert "An" in speakers
    assert "Binh" in speakers
    assert payload["audio_path"] == str(audio_path)


def test_speaker_timeline_path_keeps_audio_suffix() -> None:
    assert speaker_timeline_path(Path("abc.opus")).name == "abc.opus.speakers.json"
