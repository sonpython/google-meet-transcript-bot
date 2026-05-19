import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from src.bot.exit_detector import ExitDetector
from src.bot.participant_tracker import ParticipantTracker

Clock = Callable[[], datetime]
Sleep = Callable[[int], Awaitable[None]]
ForceExit = Callable[[], Awaitable[bool] | bool]


class MeetMonitor:
    def __init__(
        self,
        page,
        poll_seconds: int = 30,
        alone_after_seconds: int = 5 * 60,
        no_one_joined_timeout_seconds: int = 30 * 60,
        post_company_min_duration_seconds: int = 10 * 60,
        max_duration: int = 4 * 3600,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        should_force_exit: ForceExit | None = None,
    ) -> None:
        self.page = page
        self.poll_seconds = poll_seconds
        self.alone_after_seconds = alone_after_seconds
        self.no_one_joined_timeout_seconds = no_one_joined_timeout_seconds
        self.post_company_min_duration_seconds = post_company_min_duration_seconds
        self.max_duration = max_duration
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleep = sleep or asyncio.sleep
        self.should_force_exit = should_force_exit
        self.detector = ExitDetector()
        self.participants = ParticipantTracker()

    async def run_until_exit(self) -> tuple[str, tuple[str, ...], int]:
        started = self.clock()
        alone_since: datetime | None = None
        had_company = False
        last_participants: list[str] = []
        while True:
            now = self.clock()
            if (now - started).total_seconds() >= self.max_duration:
                return "hard_cap", tuple(last_participants), int((now - started).total_seconds())
            last_participants = await self.participants.get_participants(self.page)
            if await self._should_force_exit():
                return "force_out", tuple(last_participants), int((now - started).total_seconds())
            if len(last_participants) > 1:
                had_company = True
            if not had_company and (now - started).total_seconds() >= self.no_one_joined_timeout_seconds:
                return "no_one_joined", tuple(last_participants), int((now - started).total_seconds())
            reason = await self.detector.check_exit_signal(self.page, len(last_participants) or None)
            if reason and reason != "alone_signal":
                return reason, tuple(last_participants), int((now - started).total_seconds())
            can_end_after_company = (now - started).total_seconds() >= self.post_company_min_duration_seconds
            if reason == "alone_signal" and had_company and can_end_after_company:
                alone_since = alone_since or now
                if now - alone_since >= timedelta(seconds=self.alone_after_seconds):
                    return "alone", tuple(last_participants), int((now - started).total_seconds())
            else:
                alone_since = None
            await self.sleep(self.poll_seconds)

    async def _should_force_exit(self) -> bool:
        if not self.should_force_exit:
            return False
        result = self.should_force_exit()
        if hasattr(result, "__await__"):
            return bool(await result)
        return bool(result)
