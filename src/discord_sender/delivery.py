from pathlib import Path

from src.discord_sender.formatter import build_inline
from src.models.meeting_result import MeetingResult


class DiscordDelivery:
    def __init__(self, client) -> None:
        self.client = client

    async def deliver(self, result: MeetingResult, notes_path: Path, summary: str) -> Path:
        await self.client.send_text(build_inline(result, summary))
        await self.client.send_document(notes_path, caption="Full meeting notes")
        return notes_path
