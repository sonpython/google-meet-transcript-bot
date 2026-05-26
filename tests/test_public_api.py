from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs

from src import health_server
from src.config import Settings
from src.models.meeting_event import MeetingEvent
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "state.db",
        audio_dir=tmp_path / "audio",
        output_dir=tmp_path / "output",
        debug_dir=tmp_path / "debug",
        screenshot_dir=tmp_path / "screenshots",
        user_email="owner@example.com",
        admin_token="test-admin-token",
    )


def _event(code: str, title: str, hour: int) -> MeetingEvent:
    return MeetingEvent(
        meet_code=code,
        event_id=f"event-{code}",
        start_utc=datetime(2026, 5, 20, hour, 0, tzinfo=UTC),
        end_utc=datetime(2026, 5, 20, hour, 30, tzinfo=UTC),
        title=title,
        organizer="owner@example.com",
        attendees=("a@example.com", "b@example.com"),
    )


def _seed(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    settings.output_dir.mkdir(parents=True)
    transcript = settings.output_dir / "transcript-weekly-sync.md"
    minutes = settings.output_dir / "meeting-minutes-weekly-sync.md"
    transcript.write_text("Transcript body", encoding="utf-8")
    minutes.write_text("Meeting minutes body", encoding="utf-8")
    screenshot_dir = settings.screenshot_dir / "abc-defg-hij"
    screenshot_dir.mkdir(parents=True)
    (screenshot_dir / "abc-defg-hij-20260520T000000Z.png").write_bytes(b"png")
    repo = MeetingsRepo(connect(settings.db_path))
    repo.upsert(_event("abc-defg-hij", "Weekly Sync", 9))
    repo.upsert(_event("xyz-abcd-efg", "Sales Review", 11))
    repo.mark_delivered(
        "abc-defg-hij",
        "/tmp/notes.md",
        transcript_path=str(transcript),
        minutes_path=str(minutes),
    )
    return settings


def test_api_list_meetings_filters_by_title_and_date(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)

    result = health_server._api_list_meetings(parse_qs("title=weekly&from=2026-05-20&to=2026-05-20"))

    assert result["pagination"]["total"] == 1
    assert result["meetings"][0]["meet_code"] == "abc-defg-hij"
    assert result["meetings"][0]["metadata"]["attendees"] == ["a@example.com", "b@example.com"]
    assert "transcript" not in result["meetings"][0]


def test_api_meeting_detail_includes_transcript_and_minutes(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)

    meeting = health_server._api_meeting_detail("abc-defg-hij")

    assert meeting["title"] == "Weekly Sync"
    assert meeting["transcript"] == "Transcript body"
    assert meeting["meeting_minutes"] == "Meeting minutes body"
    assert meeting["files"]["transcript"]["exists"] is True
    assert meeting["files"]["screenshots"][0]["exists"] is True
    assert meeting["files"]["screenshots"][0]["index"] == 0


def test_api_transcripts_can_find_by_meeting_code(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)

    result = health_server._api_transcripts(parse_qs("meet_code=abcdefghij"))

    assert result["count"] == 1
    assert result["meetings"][0]["meet_code"] == "abc-defg-hij"
    assert result["meetings"][0]["transcript"] == "Transcript body"
