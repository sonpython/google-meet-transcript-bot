from datetime import UTC, datetime, timedelta

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
