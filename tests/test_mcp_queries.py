import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.mcp_server import queries
from src.models.meeting_event import MeetingEvent
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    db_path = tmp_path / "state.db"
    output = tmp_path / "output"
    output.mkdir()
    transcript = output / "transcript-weekly-sync.md"
    transcript.write_text("Alice said the deadline moved to Friday.", encoding="utf-8")
    minutes = output / "meeting-minutes-weekly-sync.md"
    minutes.write_text("Minutes body", encoding="utf-8")
    conn = connect(db_path)
    repo = MeetingsRepo(conn)
    repo.upsert(
        MeetingEvent(
            meet_code="abc-defg-hij",
            event_id="ev1",
            start_utc=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            end_utc=None,
            title="Weekly Sync",
            organizer="owner@example.com",
            attendees=("a@example.com",),
        )
    )
    repo.upsert(
        MeetingEvent(
            meet_code="xyz-abcd-efg",
            event_id="ev2",
            start_utc=datetime(2026, 5, 21, 9, 0, tzinfo=UTC),
            end_utc=None,
            title="Sales Review",
            organizer="sales@example.com",
            attendees=("b@example.com",),
        )
    )
    repo.mark_delivered(
        "abc-defg-hij", str(output / "notes.md"), transcript_path=str(transcript), minutes_path=str(minutes)
    )
    conn.close()
    return db_path


def test_read_only_connect_rejects_writes(seeded: Path) -> None:
    conn = queries.read_only_connect(seeded)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO failures (component, count) VALUES ('x', 1)")
    finally:
        conn.close()


def test_list_meetings_defaults_newest_first(seeded: Path) -> None:
    rows = queries.list_meetings(seeded)
    assert [row["meet_code"] for row in rows] == ["xyz-abcd-efg", "abc-defg-hij"]
    assert rows[0]["attendees"] == ["b@example.com"]
    assert "transcript" not in rows[0]


def test_list_meetings_filters_match_rest_semantics(seeded: Path) -> None:
    assert [r["meet_code"] for r in queries.list_meetings(seeded, query="weekly")] == ["abc-defg-hij"]
    assert [r["meet_code"] for r in queries.list_meetings(seeded, attendee="B@example.com")] == ["xyz-abcd-efg"]
    assert [r["meet_code"] for r in queries.list_meetings(seeded, status="delivered")] == ["abc-defg-hij"]
    assert [r["meet_code"] for r in queries.list_meetings(seeded, date_from="2026-05-21")] == ["xyz-abcd-efg"]
    assert queries.list_meetings(seeded, date_to="2026-05-19") == []
    assert len(queries.list_meetings(seeded, limit=1)) == 1


def test_get_meeting_known_and_unknown(seeded: Path) -> None:
    meeting = queries.get_meeting(seeded, "https://meet.google.com/abc-defg-hij")
    assert meeting["title"] == "Weekly Sync"
    assert meeting["meeting_minutes"] == "Minutes body"
    assert "transcript" not in meeting
    with pytest.raises(ValueError, match="meeting not found"):
        queries.get_meeting(seeded, "zzz-zzzz-zzz")
    with pytest.raises(ValueError, match="invalid Meet code"):
        queries.get_meeting(seeded, "not a code")


def test_get_transcript_and_missing_file(seeded: Path) -> None:
    text = queries.read_transcript(seeded, "abc-defg-hij")
    assert "deadline moved to Friday" in text
    missing = queries.read_transcript(seeded, "xyz-abcd-efg")
    assert "No transcript file is available" in missing


def test_get_transcript_truncates_over_cap(seeded: Path, monkeypatch) -> None:
    monkeypatch.setattr(queries, "MAX_TRANSCRIPT_CHARS", 10)
    text = queries.read_transcript(seeded, "abc-defg-hij")
    assert text.startswith("Alice said"[:10])
    assert queries.TRUNCATION_MARKER in text


def test_search_transcripts_hit_miss_and_limit(seeded: Path) -> None:
    hits = queries.search_transcripts(seeded, "DEADLINE")
    assert len(hits) == 1
    assert hits[0]["meet_code"] == "abc-defg-hij"
    assert "deadline" in hits[0]["snippet"].lower()
    assert queries.search_transcripts(seeded, "nonexistent phrase") == []
    assert queries.search_transcripts(seeded, "deadline", limit=1) == hits
    with pytest.raises(ValueError):
        queries.search_transcripts(seeded, "   ")


def test_reader_sees_writer_updates_without_lock_errors(seeded: Path) -> None:
    reader = queries.read_only_connect(seeded)
    try:
        writer = connect(seeded)
        MeetingsRepo(writer).upsert(
            MeetingEvent(
                meet_code="new-meet-ing",
                event_id="ev3",
                start_utc=datetime(2026, 5, 22, 9, 0, tzinfo=UTC),
                end_utc=None,
                title="Fresh",
                organizer="owner@example.com",
                attendees=(),
            )
        )
        writer.close()
        codes = [r["meet_code"] for r in queries.list_meetings(seeded)]
        assert "new-meet-ing" in codes
    finally:
        reader.close()


def test_db_file_not_modified_by_reads(seeded: Path) -> None:
    before = seeded.stat().st_mtime_ns
    queries.list_meetings(seeded)
    queries.get_meeting(seeded, "abc-defg-hij")
    queries.read_transcript(seeded, "abc-defg-hij")
    assert seeded.stat().st_mtime_ns == before
