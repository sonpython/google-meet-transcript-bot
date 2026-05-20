import pytest

from src import runtime_audio


def test_safe_session_sink_name_sanitizes_meet_code() -> None:
    assert runtime_audio.safe_session_sink_name("AbC-Defg-Hij") == "meet_capture_abc_defg_hij"


def test_create_session_sink_rejects_unsafe_name() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        runtime_audio.create_session_sink("meet_capture_bad;rm")


def test_create_and_remove_session_sink_use_pactl(monkeypatch) -> None:
    calls = []

    class Result:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:4] == ["pactl", "list", "short", "modules"]:
            if len(calls) > 2:
                return Result(stdout="41\tmodule-null-sink\tsink_name=meet_capture_abc\n")
            return Result(stdout="")
        if args[:4] == ["pactl", "list", "short", "sources"]:
            return Result(stdout="1\tmeet_capture_abc.monitor\tmodule-null-sink.c\t...\n")
        return Result(stdout="41\n")

    monkeypatch.setattr(runtime_audio.subprocess, "run", fake_run)

    monitor = runtime_audio.create_session_sink("meet_capture_abc")
    runtime_audio.remove_session_sink("meet_capture_abc")

    assert monitor == "meet_capture_abc.monitor"
    assert any(call[:3] == ["pactl", "load-module", "module-null-sink"] for call in calls)
    assert any(call == ["pactl", "unload-module", "41"] for call in calls)
