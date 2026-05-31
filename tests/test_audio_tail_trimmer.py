import subprocess

from src.bot.audio_tail_trimmer import trim_trailing_silence_after_participants_left


def test_trims_tail_when_participants_left_tail_is_silent(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "meeting.opus"
    audio.write_bytes(b"original")

    def fake_run(cmd, **kwargs):
        if "volumedetect" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stderr="max_volume: -55.0 dB")
        output = tmp_path / "meeting-trimmed.opus"
        output.write_bytes(b"trimmed")
        return subprocess.CompletedProcess(cmd, 0, stderr="")

    monkeypatch.setattr("src.bot.audio_tail_trimmer.subprocess.run", fake_run)

    result = trim_trailing_silence_after_participants_left(audio, keep_seconds=120, original_duration_seconds=420)

    assert result.trimmed is True
    assert result.audio_path == tmp_path / "meeting-trimmed.opus"
    assert result.duration_seconds == 120


def test_keeps_audio_when_tail_contains_sound(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "meeting.opus"
    audio.write_bytes(b"original")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stderr="max_volume: -12.0 dB")

    monkeypatch.setattr("src.bot.audio_tail_trimmer.subprocess.run", fake_run)

    result = trim_trailing_silence_after_participants_left(audio, keep_seconds=120, original_duration_seconds=420)

    assert result.trimmed is False
    assert result.reason == "tail_not_silent"
    assert result.audio_path == audio


def test_keeps_audio_when_tail_is_short(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "meeting.opus"
    audio.write_bytes(b"original")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stderr="max_volume: -55.0 dB")

    monkeypatch.setattr("src.bot.audio_tail_trimmer.subprocess.run", fake_run)

    result = trim_trailing_silence_after_participants_left(audio, keep_seconds=400, original_duration_seconds=420)

    assert result.trimmed is False
    assert result.reason == "tail_too_short"
    assert calls == []
