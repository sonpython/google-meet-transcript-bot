from datetime import UTC, datetime
from pathlib import Path

from src.models.meeting_event import MeetingEvent
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo


def _event(code: str = "abc-defg-hij") -> MeetingEvent:
    return MeetingEvent(
        meet_code=code,
        event_id="event-1",
        start_utc=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
        title="Weekly Sync",
        organizer="owner@example.com",
        attendees=("a@example.com",),
    )


def test_upsert_and_pending_round_trip(tmp_path: Path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))

    assert repo.upsert(_event())
    assert not repo.upsert(_event())

    pending = repo.get_pending()
    assert len(pending) == 1
    assert pending[0]["meet_code"] == "abc-defg-hij"


def test_terminal_meeting_is_not_rescheduled(tmp_path: Path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))

    assert repo.upsert(_event())
    repo.mark_delivered("abc-defg-hij", "/data/output/notes.md")

    changed = repo.upsert(_event())

    assert not changed
    assert repo.get("abc-defg-hij")["status"] == "delivered"


def test_mark_status_updates_fields(tmp_path: Path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    repo.upsert(_event())

    repo.mark_status("abc-defg-hij", "processing", audio_path="/tmp/audio.opus")

    row = repo.get("abc-defg-hij")
    assert row["status"] == "processing"
    assert row["audio_path"] == "/tmp/audio.opus"


def test_force_out_command_round_trip(tmp_path: Path) -> None:
    repo = MeetingsRepo(connect(tmp_path / "state.db"))
    repo.upsert(_event())

    command_id = repo.request_force_out("abc-defg-hij")
    command = repo.claim_pending_force_out("abc-defg-hij")

    assert command["id"] == command_id
    assert command["command"] == "force_out"
    assert not repo.claim_pending_force_out("abc-defg-hij")
