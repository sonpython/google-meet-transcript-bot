from src.models.meeting_result import MeetingResult
from src.telegram_sender.formatter import extract_tldr


def build_inline(result: MeetingResult, summary: str) -> str:
    participants = ", ".join(result.participant_names) or "Không rõ"
    text = (
        f"**{result.title or result.meet_code}**\n"
        f"Duration: {result.duration_sec}s\n"
        f"Participants ({len(result.participant_names)}): {participants}\n"
        f"Exit: {result.exit_reason}\n\n"
        f"**TL;DR**\n{extract_tldr(summary)}\n\n"
        "Full notes attached."
    )
    return text[:1900]
