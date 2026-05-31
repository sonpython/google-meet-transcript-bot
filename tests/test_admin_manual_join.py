from pathlib import Path
import asyncio
from datetime import UTC, datetime, timedelta

from src import health_server
from src import main as app_main
from src.config import Settings
from src.models.meeting_event import MeetingEvent
from src.state.db import connect


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "state.db",
        audio_dir=tmp_path / "audio",
        output_dir=tmp_path / "output",
        debug_dir=tmp_path / "debug",
        user_email="owner@example.com",
    )


def test_normalize_meet_code_accepts_code_and_url() -> None:
    assert health_server._normalize_meet_code("vdr-vpwr-nud") == "vdr-vpwr-nud"
    assert health_server._normalize_meet_code("https://meet.google.com/vdr-vpwr-nud?authuser=0") == "vdr-vpwr-nud"
    assert health_server._normalize_meet_code("VDRVPWRNUD") == "vdr-vpwr-nud"
    assert health_server._normalize_meet_code("not a meet") is None


def test_manual_join_creates_meeting_and_command(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)

    result = health_server._request_manual_join({"meet_code": "https://meet.google.com/vdr-vpwr-nud"})

    assert result["ok"] is True
    assert result["meet_code"] == "vdr-vpwr-nud"
    conn = connect(settings.db_path)
    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='vdr-vpwr-nud'").fetchone()
    command = conn.execute("SELECT * FROM admin_commands WHERE meet_code='vdr-vpwr-nud'").fetchone()
    assert meeting["title"] == "Manual Meet vdr-vpwr-nud"
    assert meeting["organizer"] == "owner@example.com"
    assert command["command"] == "rejoin"
    assert command["status"] == "pending"


def test_manual_join_future_calendar_meeting_requires_choice(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    future = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    monkeypatch.setattr(
        health_server,
        "_find_calendar_meeting",
        lambda meet_code, _settings: MeetingEvent(
            meet_code=meet_code,
            event_id="calendar-1",
            start_utc=future,
            end_utc=future + timedelta(hours=1),
            title="Future Review",
            organizer="owner@example.com",
            attendees=(),
        ),
    )

    result = health_server._request_manual_join({"meet_code": "abc-defg-hij"})

    assert result["needs_schedule_choice"] is True
    conn = connect(settings.db_path)
    command = conn.execute("SELECT * FROM admin_commands WHERE meet_code='abc-defg-hij'").fetchone()
    assert command is None


def test_manual_join_future_calendar_meeting_can_schedule_or_join_now(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    future = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    monkeypatch.setattr(
        health_server,
        "_find_calendar_meeting",
        lambda meet_code, _settings: MeetingEvent(
            meet_code=meet_code,
            event_id="calendar-1",
            start_utc=future,
            end_utc=future + timedelta(hours=1),
            title="Future Review",
            organizer="owner@example.com",
            attendees=(),
        ),
    )

    scheduled = health_server._request_manual_join({"meet_code": "abc-defg-hij", "mode": "scheduled"})
    now = health_server._request_manual_join({"meet_code": "abc-defg-hij", "mode": "join_now"})

    assert scheduled["ok"] is True
    assert scheduled["mode"] == "scheduled"
    assert now["ok"] is True
    assert now["mode"] == "join_now"
    conn = connect(settings.db_path)
    commands = conn.execute(
        "SELECT command FROM admin_commands WHERE meet_code='abc-defg-hij' ORDER BY id"
    ).fetchall()
    assert [row["command"] for row in commands] == ["join_scheduled", "rejoin"]


def test_event_meet_code_extracts_hangout_link() -> None:
    event = {"hangoutLink": "https://meet.google.com/arq-guqp-pvd?authuser=0"}

    assert health_server._event_meet_code(event) == "arq-guqp-pvd"


def test_regenerate_saves_instruction_and_queues_command(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'recorded')
        """
    )
    conn.commit()
    conn.close()

    result = health_server._request_regenerate(
        "abc-defg-hij",
        {"admin_instruction": "Map Sơn to Michael."},
    )

    assert result["ok"] is True
    conn = connect(settings.db_path)
    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    command = conn.execute("SELECT * FROM admin_commands WHERE meet_code='abc-defg-hij'").fetchone()
    assert meeting["admin_instruction"] == "Map Sơn to Michael."
    assert meeting["processing_status"] == "queued"
    assert meeting["processing_stage"] == "queued"
    assert meeting["processing_total"] == 1
    assert command["command"] == "regenerate"


def test_delete_meeting_removes_record_and_admin_commands(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'scheduled')
        """
    )
    conn.execute(
        "INSERT INTO admin_commands (command, meet_code, status) VALUES ('rejoin', 'abc-defg-hij', 'pending')"
    )
    conn.commit()
    conn.close()

    result = health_server._delete_meeting("abc-defg-hij")

    assert result == {"ok": True, "meet_code": "abc-defg-hij"}
    conn = connect(settings.db_path)
    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    command = conn.execute("SELECT * FROM admin_commands WHERE meet_code='abc-defg-hij'").fetchone()
    assert meeting is None
    assert command is None


def test_delete_meeting_rejects_recording(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'recording')
        """
    )
    conn.commit()
    conn.close()

    result = health_server._delete_meeting("abc-defg-hij")

    assert result["error"] == "meeting is recording; stop it before deleting"
    conn = connect(settings.db_path)
    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    assert meeting is not None


def test_regenerate_requires_instruction(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'recorded')
        """
    )
    conn.commit()
    conn.close()

    result = health_server._request_regenerate("abc-defg-hij", {"admin_instruction": "  "})

    assert result["error"] == "admin instruction is required"
    conn = connect(settings.db_path)
    command = conn.execute("SELECT * FROM admin_commands WHERE meet_code='abc-defg-hij'").fetchone()
    assert command is None


def test_regenerate_transcript_queues_command_when_audio_exists(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    settings.audio_dir.mkdir(parents=True)
    (settings.audio_dir / "abc-defg-hij.opus").write_bytes(b"audio")
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status, transcript_path, minutes_path)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'delivered', '/tmp/bad.md', '/tmp/minutes.md')
        """
    )
    conn.commit()
    conn.close()

    result = health_server._request_regenerate_transcript("abc-defg-hij")

    assert result["ok"] is True
    conn = connect(settings.db_path)
    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    command = conn.execute("SELECT * FROM admin_commands WHERE meet_code='abc-defg-hij'").fetchone()
    assert meeting["processing_status"] == "queued"
    assert meeting["processing_stage"] == "queued_transcript"
    assert command["command"] == "regenerate_transcript"


def test_regenerate_transcript_requires_audio(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(health_server, "load_settings", lambda: settings)
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'delivered')
        """
    )
    conn.commit()
    conn.close()

    result = health_server._request_regenerate_transcript("abc-defg-hij")

    assert result["error"] == "no audio files found"


def test_regenerate_transcript_command_uses_audio_without_instruction(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.audio_dir.mkdir(parents=True)
    settings.output_dir.mkdir(parents=True)
    audio_path = settings.audio_dir / "abc-defg-hij.opus"
    audio_path.write_bytes(b"audio")
    transcript_path = settings.output_dir / "transcript-weekly-sync.md"

    class Processor:
        async def process_many(self, results, append=True, on_progress=None, generate_documents=False):
            transcript_path.write_text("Fresh transcript", encoding="utf-8")
            return (transcript_path,)

    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status, transcript_path, minutes_path)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'delivered', '/tmp/bad.md', '/tmp/minutes.md')
        """
    )
    command_id = conn.execute(
        "INSERT INTO admin_commands (command, meet_code, status) VALUES ('regenerate_transcript', 'abc-defg-hij', 'running')"
    ).lastrowid
    conn.commit()
    conn.close()

    asyncio.run(
        app_main._run_regenerate_command(
            settings,
            {"id": command_id, "command": "regenerate_transcript", "meet_code": "abc-defg-hij"},
            Processor(),
        )
    )

    conn = connect(settings.db_path)
    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    command = conn.execute("SELECT * FROM admin_commands WHERE id=?", (command_id,)).fetchone()
    assert meeting["transcript_path"] == str(transcript_path)
    assert meeting["minutes_path"] is None
    assert meeting["summary_path"] is None
    assert meeting["notes_path"] == str(transcript_path)
    assert command["status"] == "done"


def test_recover_interrupted_admin_commands_marks_running_regenerate_failed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = connect(settings.db_path)
    conn.execute(
        """
        INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, status, processing_status, processing_stage)
        VALUES ('abc-defg-hij', 'event-1', '2026-05-20T09:00:00+00:00', 'Weekly Sync', 'delivered', 'running', 'transcribing')
        """
    )
    command_id = conn.execute(
        "INSERT INTO admin_commands (command, meet_code, status) VALUES ('regenerate_transcript', 'abc-defg-hij', 'running')"
    ).lastrowid
    conn.commit()
    repo = app_main.MeetingsRepo(conn)

    app_main._recover_interrupted_admin_commands(repo)

    meeting = conn.execute("SELECT * FROM meetings WHERE meet_code='abc-defg-hij'").fetchone()
    command = conn.execute("SELECT * FROM admin_commands WHERE id=?", (command_id,)).fetchone()
    assert command["status"] == "failed"
    assert command["error"] == "interrupted by service restart"
    assert meeting["processing_status"] == "failed"
    assert meeting["processing_stage"] == "failed"
    assert meeting["processing_error"] == "interrupted by service restart"
