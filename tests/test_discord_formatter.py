from pathlib import Path

from src.discord_sender.formatter import build_inline
from src.models.meeting_result import MeetingResult


def test_build_inline_is_discord_markdown() -> None:
    result = MeetingResult(
        meet_code="abc-defg-hij",
        audio_path=Path("audio.opus"),
        duration_sec=3484,
        exit_reason="alone",
        participant_names=("An",),
        title="Weekly Sync",
    )

    text = build_inline(result, "## TL;DR\n- Done\n\n## Actions\n- Next")

    assert "**Weekly Sync**" in text
    assert "Duration: 58m 4s" in text
    assert "**TL;DR**" in text
    assert "- Done" in text
    assert "Exit" not in text
    assert "alone" not in text
