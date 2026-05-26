from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.bot.meeting_session import MeetingSession
from src.models.meeting_event import MeetingEvent


class FakeRepo:
    def __init__(self) -> None:
        self.statuses = []

    def mark_status(self, meet_code, status, last_error=None, audio_path=None, **fields):
        self.statuses.append((meet_code, status, last_error, audio_path, fields))

    def mark_delivered(self, meet_code, notes_path, **extra_paths):
        self.statuses.append((meet_code, "delivered", notes_path, extra_paths))

    def mark_processing(self, meet_code, status, batch=0, total=0, error=None, stage=None):
        self.statuses.append((meet_code, f"processing:{status}", batch, total, error, stage))

    def get(self, meet_code):
        return {"admin_instruction": ""}

    def claim_pending_force_out(self, meet_code):
        return None


class FakeBrowserSession:
    page = object()

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBrowserFactory:
    def __init__(self) -> None:
        self.pulse_sinks = []

    async def launch_with_state(self, pulse_sink=None):
        self.pulse_sinks.append(pulse_sink)
        return FakeBrowserSession()


class FakeRecorder:
    starts = []

    def __init__(self, audio_dir, audio_source):
        self.audio_dir = Path(audio_dir)
        self.audio_source = audio_source
        self.running = False
        self.output_path = None

    def start(self, meet_code, audio_source=None):
        self.running = True
        self.output_path = self.audio_dir / f"{meet_code}.opus"
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"opus")
        self.starts.append((meet_code, audio_source))
        return self.output_path

    def stop(self):
        self.running = False
        return self.output_path

    def is_running(self):
        return self.running

    def error_tail(self):
        return ""


class FakeJoinResult:
    admitted = True
    status = "joined"
    error_msg = None


class FakeMeetJoiner:
    async def join(self, page, meet_code, display_name):
        return FakeJoinResult()


class FakeMeetMonitor:
    def __init__(self, page, should_force_exit, health_check=None):
        pass

    async def run_until_exit(self):
        return "alone_timeout", ["Host", "Bot"], 30, datetime(2026, 5, 20, tzinfo=UTC)


def meeting(code: str, end_utc=None) -> MeetingEvent:
    return MeetingEvent(
        meet_code=code,
        event_id=code,
        start_utc=datetime.now(UTC),
        end_utc=end_utc,
        title=code,
        organizer=None,
        attendees=(),
    )


async def fake_process_result(result):
    audio_path = result.audio_path
    output_dir = audio_path.parent
    return output_dir / "transcript.md", output_dir / "summary.md", output_dir / "notes.md"


class FakeScreenshotCapturer:
    events = []

    def __init__(self, page, screenshot_dir, meet_code, interval_seconds):
        self.page = page
        self.screenshot_dir = Path(screenshot_dir)
        self.meet_code = meet_code
        self.interval_seconds = interval_seconds

    def start(self):
        self.events.append(("start", self.meet_code, self.screenshot_dir, self.interval_seconds))

    async def stop(self):
        self.events.append(("stop", self.meet_code, self.screenshot_dir, self.interval_seconds))


@pytest.mark.anyio
async def test_session_uses_distinct_sink_and_monitor_per_meeting(tmp_path, monkeypatch) -> None:
    created = []
    removed = []
    FakeRecorder.starts = []

    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", FakeRecorder)
    monkeypatch.setattr("src.bot.meeting_session.MeetJoiner", FakeMeetJoiner)
    monkeypatch.setattr("src.bot.meeting_session.MeetMonitor", FakeMeetMonitor)
    monkeypatch.setattr(
        "src.bot.meeting_session.create_session_sink",
        lambda sink: created.append(sink) or f"{sink}.monitor",
    )
    monkeypatch.setattr("src.bot.meeting_session.remove_session_sink", lambda sink: removed.append(sink))

    factory = FakeBrowserFactory()
    session = MeetingSession(
        FakeRepo(),
        factory,
        tmp_path,
        "meet_capture.monitor",
        "Bot",
        fake_process_result,
    )

    await session.run(meeting("abc-defg-hij"))
    await session.run(meeting("xyz-uvwx-rst"))
    await session.wait_for_processing()

    assert created == ["meet_capture_abc_defg_hij", "meet_capture_xyz_uvwx_rst"]
    assert factory.pulse_sinks == created
    assert FakeRecorder.starts == [
        ("abc-defg-hij", "meet_capture_abc_defg_hij.monitor"),
        ("xyz-uvwx-rst", "meet_capture_xyz_uvwx_rst.monitor"),
    ]
    assert removed == created


@pytest.mark.anyio
async def test_session_removes_sink_when_join_fails(tmp_path, monkeypatch) -> None:
    removed = []

    class DeniedJoiner:
        async def join(self, page, meet_code, display_name):
            result = FakeJoinResult()
            result.admitted = False
            result.status = "denied"
            return result

    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", FakeRecorder)
    monkeypatch.setattr("src.bot.meeting_session.MeetJoiner", DeniedJoiner)
    monkeypatch.setattr("src.bot.meeting_session.create_session_sink", lambda sink: f"{sink}.monitor")
    monkeypatch.setattr("src.bot.meeting_session.remove_session_sink", lambda sink: removed.append(sink))

    session = MeetingSession(
        FakeRepo(),
        FakeBrowserFactory(),
        tmp_path,
        "meet_capture.monitor",
        "Bot",
        fake_process_result,
    )

    await session.run(meeting("abc-defg-hij"))

    assert removed == ["meet_capture_abc_defg_hij"]


@pytest.mark.anyio
async def test_session_starts_and_stops_screenshot_capture_while_recording(tmp_path, monkeypatch) -> None:
    FakeScreenshotCapturer.events = []

    class AloneMonitor:
        def __init__(self, page, should_force_exit, health_check=None):
            pass

        async def run_until_exit(self):
            return "alone", ["Host", "Bot"], 30, datetime(2026, 5, 20, tzinfo=UTC)

    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", FakeRecorder)
    monkeypatch.setattr("src.bot.meeting_session.MeetJoiner", FakeMeetJoiner)
    monkeypatch.setattr("src.bot.meeting_session.MeetMonitor", AloneMonitor)
    monkeypatch.setattr("src.bot.meeting_session.PeriodicScreenshotCapturer", FakeScreenshotCapturer)
    monkeypatch.setattr("src.bot.meeting_session.create_session_sink", lambda sink: f"{sink}.monitor")
    monkeypatch.setattr("src.bot.meeting_session.remove_session_sink", lambda sink: None)

    screenshot_dir = tmp_path / "screenshots"
    session = MeetingSession(
        FakeRepo(),
        FakeBrowserFactory(),
        tmp_path / "audio",
        "meet_capture.monitor",
        "Bot",
        fake_process_result,
        screenshot_dir=screenshot_dir,
        screenshot_interval_seconds=300,
    )

    await session.run(meeting("abc-defg-hij"))

    assert FakeScreenshotCapturer.events == [
        ("start", "abc-defg-hij", screenshot_dir, 300),
        ("stop", "abc-defg-hij", screenshot_dir, 300),
    ]


@pytest.mark.anyio
async def test_session_auto_rejoins_after_page_closed(tmp_path, monkeypatch) -> None:
    removed = []
    processed = []

    class UniqueRecorder(FakeRecorder):
        starts = []
        counter = 0

        def start(self, meet_code, audio_source=None):
            self.running = True
            UniqueRecorder.counter += 1
            self.output_path = self.audio_dir / f"{meet_code}-{UniqueRecorder.counter}.opus"
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_bytes(b"opus")
            self.starts.append((meet_code, audio_source))
            return self.output_path

    class PageClosedThenAloneMonitor:
        calls = 0

        def __init__(self, page, should_force_exit, health_check=None):
            pass

        async def run_until_exit(self):
            PageClosedThenAloneMonitor.calls += 1
            if PageClosedThenAloneMonitor.calls == 1:
                return "page_closed", ["Host", "Bot"], 10, datetime(2026, 5, 20, tzinfo=UTC)
            return "alone", ["Host", "Bot"], 20, datetime(2026, 5, 20, 0, 1, tzinfo=UTC)

    async def process_result(result):
        processed.append(result.audio_path.name)
        return await fake_process_result(result)

    monkeypatch.setattr("src.bot.meeting_session.AUTO_REJOIN_DELAY_SECONDS", 0)
    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", UniqueRecorder)
    monkeypatch.setattr("src.bot.meeting_session.MeetJoiner", FakeMeetJoiner)
    monkeypatch.setattr("src.bot.meeting_session.MeetMonitor", PageClosedThenAloneMonitor)
    monkeypatch.setattr("src.bot.meeting_session.create_session_sink", lambda sink: f"{sink}.monitor")
    monkeypatch.setattr("src.bot.meeting_session.remove_session_sink", lambda sink: removed.append(sink))

    session = MeetingSession(
        FakeRepo(),
        FakeBrowserFactory(),
        tmp_path,
        "meet_capture.monitor",
        "Bot",
        process_result,
    )

    await session.run(meeting("abc-defg-hij"))
    await session.wait_for_processing()

    assert PageClosedThenAloneMonitor.calls == 2
    assert removed == ["meet_capture_abc_defg_hij", "meet_capture_abc_defg_hij"]
    assert processed == ["abc-defg-hij-1.opus", "abc-defg-hij-2.opus"]


@pytest.mark.anyio
async def test_session_auto_rejoins_after_page_closed_even_after_calendar_end(tmp_path, monkeypatch) -> None:
    class PageClosedThenAloneMonitor:
        calls = 0

        def __init__(self, page, should_force_exit, health_check=None):
            pass

        async def run_until_exit(self):
            PageClosedThenAloneMonitor.calls += 1
            if PageClosedThenAloneMonitor.calls == 1:
                return "page_closed", ["Host", "Bot"], 10, datetime.now(UTC)
            return "alone", ["Host", "Bot"], 20, datetime.now(UTC)

    monkeypatch.setattr("src.bot.meeting_session.AUTO_REJOIN_DELAY_SECONDS", 0)
    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", FakeRecorder)
    monkeypatch.setattr("src.bot.meeting_session.MeetJoiner", FakeMeetJoiner)
    monkeypatch.setattr("src.bot.meeting_session.MeetMonitor", PageClosedThenAloneMonitor)
    monkeypatch.setattr("src.bot.meeting_session.create_session_sink", lambda sink: f"{sink}.monitor")
    monkeypatch.setattr("src.bot.meeting_session.remove_session_sink", lambda sink: None)

    session = MeetingSession(
        FakeRepo(),
        FakeBrowserFactory(),
        tmp_path,
        "meet_capture.monitor",
        "Bot",
        fake_process_result,
    )

    await session.run(meeting("abc-defg-hij", end_utc=datetime(2026, 1, 1, tzinfo=UTC)))

    assert PageClosedThenAloneMonitor.calls == 2


@pytest.mark.anyio
async def test_session_does_not_process_when_end_is_not_confirmed(tmp_path, monkeypatch) -> None:
    processed = []

    class AlwaysPageClosedMonitor:
        def __init__(self, page, should_force_exit, health_check=None):
            pass

        async def run_until_exit(self):
            return "page_closed", ["Host", "Bot"], 10, datetime.now(UTC)

    async def process_result(result):
        processed.append(result.audio_path)
        return await fake_process_result(result)

    monkeypatch.setattr("src.bot.meeting_session.MAX_AUTO_REJOINS", 0)
    monkeypatch.setattr("src.bot.recorder_supervisor.AudioRecorder", FakeRecorder)
    monkeypatch.setattr("src.bot.meeting_session.MeetJoiner", FakeMeetJoiner)
    monkeypatch.setattr("src.bot.meeting_session.MeetMonitor", AlwaysPageClosedMonitor)
    monkeypatch.setattr("src.bot.meeting_session.create_session_sink", lambda sink: f"{sink}.monitor")
    monkeypatch.setattr("src.bot.meeting_session.remove_session_sink", lambda sink: None)

    repo = FakeRepo()
    session = MeetingSession(
        repo,
        FakeBrowserFactory(),
        tmp_path,
        "meet_capture.monitor",
        "Bot",
        process_result,
    )

    await session.run(meeting("abc-defg-hij"))
    await session.wait_for_processing()

    assert processed == []
    assert repo.statuses[-1][1] == "recorded"
    assert repo.statuses[-1][2] == "meeting end not confirmed: page_closed"
    assert repo.statuses[-1][4]["meeting_end_confirmed"] == 0
