import pytest

from src.bot.audio_recorder import AudioRecorder


def test_recorder_fails_fast_when_audio_source_missing(tmp_path) -> None:
    recorder = AudioRecorder(tmp_path, audio_source="definitely_missing_source", ffmpeg_bin="ffmpeg")

    with pytest.raises(RuntimeError, match="ffmpeg audio source failed"):
        recorder.start("abc-defg-hij")
