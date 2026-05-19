import asyncio
import inspect
from collections.abc import Awaitable, Callable

import structlog

from src.calendar_watcher.classifier import to_meeting_event
from src.models.meeting_event import MeetingEvent

MeetingHandler = Callable[[MeetingEvent], Awaitable[None] | None]


class CalendarWatcher:
    def __init__(
        self,
        calendar_client,
        user_email: str,
        on_meeting: MeetingHandler,
        poll_interval_seconds: int = 300,
        lookahead_minutes: int = 60,
    ) -> None:
        self.calendar_client = calendar_client
        self.user_email = user_email
        self.on_meeting = on_meeting
        self.poll_interval_seconds = poll_interval_seconds
        self.lookahead_minutes = lookahead_minutes
        self.log = structlog.get_logger(__name__)

    async def poll_once(self) -> int:
        count = 0
        for event in self.calendar_client.list_upcoming(self.lookahead_minutes):
            meeting = to_meeting_event(event, self.user_email)
            if not meeting:
                continue
            result = self.on_meeting(meeting)
            if inspect.isawaitable(result):
                await result
            count += 1
        self.log.info("calendar_poll_complete", qualifying_events=count)
        return count

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                self.log.exception("calendar_poll_failed")
            await asyncio.sleep(self.poll_interval_seconds)
