import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from sqlite3 import Row

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.models.meeting_event import MeetingEvent
from src.state.meetings_repo import MeetingsRepo

LATE_START_GRACE = timedelta(minutes=30)


class JobRunner:
    def __init__(self, repo: MeetingsRepo, run_meeting, max_concurrent_meetings: int = 3) -> None:
        self.repo = repo
        self.run_meeting = run_meeting
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_meetings))
        self.scheduler = AsyncIOScheduler(timezone=UTC)

    def start(self) -> None:
        self.scheduler.start()
        self.resume_pending()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    def schedule_bot_join(self, meeting: MeetingEvent) -> None:
        existing = self.repo.get(meeting.meet_code)
        if existing and existing["status"] in {"delivered", "failed", "cancelled", "no_one_joined"}:
            return
        self.repo.upsert(meeting)
        self._schedule(meeting, f"meet:{meeting.meet_code}")

    def schedule_manual_join(self, meeting: MeetingEvent, command_id: int) -> None:
        self.repo.mark_status(meeting.meet_code, "scheduled", None)
        self._schedule(meeting, f"rejoin:{meeting.meet_code}:{command_id}", immediate=True)

    def _schedule(self, meeting: MeetingEvent, job_id: str, immediate: bool = False) -> None:
        run_date = meeting.start_utc - timedelta(seconds=60)
        if immediate or run_date < datetime.now(UTC):
            run_date = datetime.now(UTC)
        self.scheduler.add_job(
            self._run_meeting_capped,
            "date",
            run_date=run_date,
            args=[meeting],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,
        )

    async def _run_meeting_capped(self, meeting: MeetingEvent) -> None:
        async with self._semaphore:
            result = self.run_meeting(meeting)
            if inspect.isawaitable(result):
                await result

    def resume_pending(self) -> None:
        now = datetime.now(UTC)
        for row in self.repo.get_pending():
            meeting = _row_to_meeting_event(row)
            if meeting.start_utc < now - LATE_START_GRACE:
                self.repo.mark_status(meeting.meet_code, "failed", "missed scheduled start during downtime")
                continue
            self.schedule_bot_join(meeting)


def _row_to_meeting_event(row: Row) -> MeetingEvent:
    return MeetingEvent(
        meet_code=row["meet_code"],
        event_id=row["event_id"],
        start_utc=datetime.fromisoformat(row["scheduled_start_utc"]).astimezone(UTC),
        end_utc=datetime.fromisoformat(row["scheduled_end_utc"]).astimezone(UTC) if row["scheduled_end_utc"] else None,
        title=row["title"],
        organizer=None,
        attendees=(),
    )
