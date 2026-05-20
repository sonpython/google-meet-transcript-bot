import pytest

from src.bot.audio_recorder import AudioRecorder


def test_recorder_fails_fast_when_audio_source_missing(tmp_path) -> None:
    recorder = AudioRecorder(tmp_path, audio_source="definitely_missing_source", ffmpeg_bin="ffmpeg")

    with pytest.raises(RuntimeError, match="ffmpeg audio source failed"):
        recorder.start("abc-defg-hij")


def test_recorder_start_uses_explicit_audio_source(tmp_path, monkeypatch) -> None:
    calls = []

    class FakeProcess:
        stderr = None

        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr("src.bot.audio_recorder.subprocess.Popen", fake_popen)
    monkeypatch.setattr("src.bot.audio_recorder.time.sleep", lambda _seconds: None)

    recorder = AudioRecorder(tmp_path, audio_source="default.monitor", ffmpeg_bin="ffmpeg")
    recorder.start("abc-defg-hij", audio_source="session.monitor")

    assert "-i" in calls[0]
    assert calls[0][calls[0].index("-i") + 1] == "session.monitor"
