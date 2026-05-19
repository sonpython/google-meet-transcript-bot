import asyncio
from datetime import UTC, datetime, timedelta

from src.bot.exit_detector import ExitDetector
from src.bot.participant_tracker import ParticipantTracker


class MeetMonitor:
    def __init__(
        self,
        page,
        poll_seconds: int = 30,
        alone_after_seconds: int = 120,
        no_one_joined_timeout_seconds: int = 30 * 60,
        max_duration: int = 4 * 3600,
    ) -> None:
        self.page = page
        self.poll_seconds = poll_seconds
        self.alone_after_seconds = alone_after_seconds
        self.no_one_joined_timeout_seconds = no_one_joined_timeout_seconds
        self.max_duration = max_duration
        self.detector = ExitDetector()
        self.participants = ParticipantTracker()

    async def run_until_exit(self) -> tuple[str, tuple[str, ...], int]:
        started = datetime.now(UTC)
        alone_since: datetime | None = None
        had_company = False
        last_participants: list[str] = []
        while True:
            now = datetime.now(UTC)
            if (now - started).total_seconds() >= self.max_duration:
                return "hard_cap", tuple(last_participants), int((now - started).total_seconds())
            last_participants = await self.participants.get_participants(self.page)
            if len(last_participants) > 1:
                had_company = True
            if not had_company and (now - started).total_seconds() >= self.no_one_joined_timeout_seconds:
                return "no_one_joined", tuple(last_participants), int((now - started).total_seconds())
            reason = await self.detector.check_exit_signal(self.page, len(last_participants) or None)
            if reason and reason != "alone_signal":
                return reason, tuple(last_participants), int((now - started).total_seconds())
            if reason == "alone_signal" and had_company:
                alone_since = alone_since or now
                if now - alone_since >= timedelta(seconds=self.alone_after_seconds):
                    return "alone", tuple(last_participants), int((now - started).total_seconds())
            else:
                alone_since = None
            await asyncio.sleep(self.poll_seconds)
