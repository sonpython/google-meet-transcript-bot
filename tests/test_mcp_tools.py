import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.config import Settings
from src.mcp_server import server as mcp_server_module
from src.models.meeting_event import MeetingEvent
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo


@pytest.fixture
def built_server(tmp_path: Path, monkeypatch):
    settings = Settings(
        db_path=tmp_path / "state.db",
        audio_dir=tmp_path / "audio",
        output_dir=tmp_path / "output",
        debug_dir=tmp_path / "debug",
        screenshot_dir=tmp_path / "screenshots",
        user_email="owner@example.com",
        admin_token="test-admin-token",
    )
    monkeypatch.setattr(mcp_server_module, "load_settings", lambda: settings)
    settings.output_dir.mkdir(parents=True)
    transcript = settings.output_dir / "transcript-weekly-sync.md"
    transcript.write_text("The roadmap was approved by everyone.", encoding="utf-8")
    conn = connect(settings.db_path)
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
    repo.mark_delivered("abc-defg-hij", str(transcript), transcript_path=str(transcript))
    conn.close()
    return mcp_server_module.build_server()


def _call(server, name: str, arguments: dict):
    return asyncio.run(server.call_tool(name, arguments))


def _payload(result):
    # Structured output when the SDK provides it (lists come wrapped as
    # {"result": [...]}), otherwise the JSON text content.
    assert not result.is_error, result.content
    data = result.structured_content
    if data is None:
        return json.loads(result.content[0].text)
    return data["result"] if set(data.keys()) == {"result"} else data


def test_all_four_tools_are_registered(built_server) -> None:
    tools = asyncio.run(built_server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {"list_meetings", "get_meeting", "get_transcript", "search_transcripts"}


def test_list_meetings_tool(built_server) -> None:
    result = _call(built_server, "list_meetings", {"query": "weekly"})
    rows = _payload(result)
    assert rows[0]["meet_code"] == "abc-defg-hij"


def test_get_meeting_and_transcript_tools(built_server) -> None:
    meeting = _payload(_call(built_server, "get_meeting", {"meet_code": "abc-defg-hij"}))
    assert meeting["title"] == "Weekly Sync"
    transcript_result = _call(built_server, "get_transcript", {"meet_code": "abc-defg-hij"})
    assert not transcript_result.is_error
    assert "roadmap was approved" in transcript_result.content[0].text


def test_unknown_meeting_surfaces_a_readable_error(built_server) -> None:
    # In-process call_tool raises; over the wire the same failure becomes an
    # is_error result. The readable message must survive either way.
    with pytest.raises(Exception) as excinfo:
        _call(built_server, "get_meeting", {"meet_code": "zzz-zzzz-zzz"})
    chain = str(excinfo.value) + str(excinfo.value.__cause__ or "")
    assert "meeting not found" in chain


def test_search_transcripts_tool(built_server) -> None:
    hits = _payload(_call(built_server, "search_transcripts", {"query": "roadmap"}))
    assert hits[0]["meet_code"] == "abc-defg-hij"
    assert "roadmap" in hits[0]["snippet"].lower()


def test_build_app_wraps_with_bearer_auth(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        db_path=tmp_path / "state.db",
        audio_dir=tmp_path / "audio",
        output_dir=tmp_path / "output",
        debug_dir=tmp_path / "debug",
        screenshot_dir=tmp_path / "screenshots",
        user_email="owner@example.com",
        admin_token="test-admin-token",
    )
    monkeypatch.setattr(mcp_server_module, "load_settings", lambda: settings)
    connect(settings.db_path).close()
    app = mcp_server_module.build_app()
    from src.mcp_server.bearer_auth import BearerAuthASGI

    assert isinstance(app, BearerAuthASGI)
    assert app.admin_token == "test-admin-token"
