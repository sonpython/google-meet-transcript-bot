from pathlib import Path

from src.models.meeting_result import MeetingResult
from src.telegram_sender.formatter import build_inline, build_notes_file, extract_tldr


def test_extract_tldr_section() -> None:
    summary = "Intro\n\n## TL;DR\n- Một\n- Hai\n\n## Decisions\nDone"

    assert extract_tldr(summary) == "- Một\n- Hai"


def test_build_inline_escapes_markdown_v2(tmp_path: Path) -> None:
    result = MeetingResult(
        meet_code="abc-defg-hij",
        audio_path=tmp_path / "audio.opus",
        duration_sec=90,
        exit_reason="empty_meeting",
        participant_names=("An_Nguyen",),
        title="Weekly (Sync)",
    )

    inline = build_inline(result, "## TL;DR\nAction [one]")

    assert "Weekly \\(Sync\\)" in inline
    assert "An\\_Nguyen" in inline
    assert "Action \\[one\\]" in inline


def test_build_notes_file(tmp_path: Path) -> None:
    path = build_notes_file(tmp_path / "notes.md", "Title", "Summary", "Transcript")

    assert path.read_text() == "# Title\n\nSummary\n\n## Transcript\n\nTranscript"
