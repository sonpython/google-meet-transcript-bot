from pathlib import Path

from src.discord_sender.formatter import build_inline
from src.models.meeting_result import MeetingResult


def test_build_inline_is_discord_markdown() -> None:
    result = MeetingResult(
        meet_code="abc-defg-hij",
        audio_path=Path("audio.opus"),
        duration_sec=42,
        exit_reason="empty_meeting",
        participant_names=("An",),
        title="Weekly Sync",
    )

    text = build_inline(result, "## TL;DR\n- Done\n\n## Actions\n- Next")

    assert "**Weekly Sync**" in text
    assert "**TL;DR**" in text
    assert "- Done" in text
