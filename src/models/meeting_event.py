from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MeetingEvent:
    meet_code: str
    event_id: str
    start_utc: datetime
    title: str
    organizer: str | None
    attendees: tuple[str, ...]
