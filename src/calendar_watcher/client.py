from datetime import UTC, datetime, timedelta
from typing import Any

from googleapiclient.discovery import build


class CalendarClient:
    def __init__(self, credentials, calendar_id: str = "primary") -> None:
        self.calendar_id = calendar_id
        self.service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def list_upcoming(self, window_minutes: int = 60) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        until = now + timedelta(minutes=window_minutes)
        response = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=now.isoformat(),
                timeMax=until.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = response.get("items", [])
        return [event for event in items if isinstance(event, dict)]
