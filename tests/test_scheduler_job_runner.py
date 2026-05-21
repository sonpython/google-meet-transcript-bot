from datetime import UTC, datetime, timedelta

import pytest

from src.models.meeting_event import MeetingEvent
from src.scheduler.job_runner import JobRunner
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo


def test_terminal_meeting_is_not_scheduled_again(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    meeting = MeetingEvent(
        meet_code="abc-defg-hij",
        event_id="event-1",
        start_utc=datetime.now(UTC) + timedelta(minutes=5),
        end_utc=None,
        title="Done",
        organizer=None,
        attendees=(),
    )
    repo.upsert(meeting)
    repo.mark_status(meeting.meet_code, "failed", "done")
    runner = JobRunner(repo, lambda event: None)

    runner.schedule_bot_join(meeting)

    assert not runner.scheduler.get_jobs()


def test_running_meeting_is_not_scheduled_again(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    meeting = MeetingEvent(
        meet_code="abc-defg-hij",
        event_id="event-1",
        start_utc=datetime.now(UTC) + timedelta(minutes=5),
        end_utc=None,
        title="Running",
        organizer=None,
        attendees=(),
    )
    repo.upsert(meeting)
    runner = JobRunner(repo, lambda event: None)
    runner._running_meet_codes.add(meeting.meet_code)

    runner.schedule_bot_join(meeting)

    assert not runner.scheduler.get_jobs()


def test_recently_missed_pending_meeting_is_resumed(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    meeting = MeetingEvent(
        meet_code="abc-defg-hij",
        event_id="event-1",
        start_utc=datetime.now(UTC) - timedelta(minutes=5),
        end_utc=None,
        title="Recent",
        organizer=None,
        attendees=(),
    )
    repo.upsert(meeting)
    runner = JobRunner(repo, lambda event: None)

    runner.resume_pending()

    assert repo.get(meeting.meet_code)["status"] == "scheduled"
    assert runner.scheduler.get_jobs()


def test_old_missed_pending_meeting_is_failed(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    meeting = MeetingEvent(
        meet_code="abc-defg-hij",
        event_id="event-1",
        start_utc=datetime.now(UTC) - timedelta(minutes=45),
        end_utc=None,
        title="Old",
        organizer=None,
        attendees=(),
    )
    repo.upsert(meeting)
    runner = JobRunner(repo, lambda event: None)

    runner.resume_pending()

    row = repo.get(meeting.meet_code)
    assert row["status"] == "failed"
    assert row["last_error"] == "missed scheduled start during downtime"


def test_in_progress_meeting_before_end_is_resumed_after_restart(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    meeting = MeetingEvent(
        meet_code="abc-defg-hij",
        event_id="event-1",
        start_utc=datetime.now(UTC) - timedelta(minutes=45),
        end_utc=datetime.now(UTC) + timedelta(minutes=15),
        title="Still live",
        organizer=None,
        attendees=(),
    )
    repo.upsert(meeting)
    runner = JobRunner(repo, lambda event: None)

    runner.resume_pending()

    assert repo.get(meeting.meet_code)["status"] == "scheduled"
    assert runner.scheduler.get_jobs()


def test_processing_meeting_is_not_failed_on_restart(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    meeting = MeetingEvent(
        meet_code="abc-defg-hij",
        event_id="event-1",
        start_utc=datetime.now(UTC) - timedelta(minutes=45),
        end_utc=datetime.now(UTC) - timedelta(minutes=10),
        title="Processing",
        organizer=None,
        attendees=(),
    )
    repo.upsert(meeting)
    repo.mark_status(meeting.meet_code, "processing")
    runner = JobRunner(repo, lambda event: None)

    runner.resume_pending()

    assert repo.get(meeting.meet_code)["status"] == "processing"
    assert not runner.scheduler.get_jobs()


@pytest.mark.anyio
async def test_run_meeting_is_capped_by_semaphore(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    running = 0
    max_seen = 0

    async def run_meeting(meeting):
        nonlocal running, max_seen
        running += 1
        max_seen = max(max_seen, running)
        await anyio_sleep(0.01)
        running -= 1

    async def anyio_sleep(seconds):
        import anyio

        await anyio.sleep(seconds)

    runner = JobRunner(repo, run_meeting, max_concurrent_meetings=1)
    first = MeetingEvent("abc-defg-hij", "1", datetime.now(UTC), None, "First", None, ())
    second = MeetingEvent("xyz-uvwx-rst", "2", datetime.now(UTC), None, "Second", None, ())

    import anyio

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(runner._run_meeting_capped, first)
        task_group.start_soon(runner._run_meeting_capped, second)

    assert max_seen == 1


@pytest.mark.anyio
async def test_same_meeting_is_not_run_twice(tmp_path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    calls = 0

    async def run_meeting(meeting):
        nonlocal calls
        calls += 1
        await anyio_sleep(0.01)

    async def anyio_sleep(seconds):
        import anyio

        await anyio.sleep(seconds)

    runner = JobRunner(repo, run_meeting, max_concurrent_meetings=2)
    meeting = MeetingEvent("abc-defg-hij", "1", datetime.now(UTC), None, "Same", None, ())

    import anyio

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(runner._run_meeting_capped, meeting)
        task_group.start_soon(runner._run_meeting_capped, meeting)

    assert calls == 1
