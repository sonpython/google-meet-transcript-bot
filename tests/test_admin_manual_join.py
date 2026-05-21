from pathlib import Path

from src import health_server
from src.config import Settings
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
    assert command["command"] == "regenerate"


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
