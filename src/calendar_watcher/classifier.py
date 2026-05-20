from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from src.models.meeting_event import MeetingEvent


def is_qualifying(event: dict[str, Any], user_email: str) -> bool:
    if not _meet_url(event):
        return False
    normalized_user = user_email.casefold()
    organizer = _email(event.get("organizer"))
    if organizer == normalized_user or _is_self(event.get("organizer")):
        return True
    for attendee in event.get("attendees", []):
        if _is_self(attendee):
            return attendee.get("responseStatus") != "declined"
        if _email(attendee) == normalized_user:
            return attendee.get("responseStatus") != "declined"
    return False


def to_meeting_event(event: dict[str, Any], user_email: str) -> MeetingEvent | None:
    if not is_qualifying(event, user_email):
        return None
    meet_url = _meet_url(event)
    start_utc = _parse_start(event)
    if not meet_url or not start_utc:
        return None
    attendees = tuple(
        attendee["email"]
        for attendee in event.get("attendees", [])
        if isinstance(attendee, dict) and attendee.get("email")
    )
    return MeetingEvent(
        meet_code=_meet_code(meet_url),
        event_id=str(event.get("id", "")),
        start_utc=start_utc,
        end_utc=_parse_end(event),
        title=str(event.get("summary") or "Untitled meeting"),
        organizer=_raw_email(event.get("organizer")),
        attendees=attendees,
    )


def _email(value: Any) -> str | None:
    raw = _raw_email(value)
    return raw.casefold() if raw else None


def _raw_email(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("email"):
        return str(value["email"])
    return None


def _is_self(value: Any) -> bool:
    return isinstance(value, dict) and value.get("self") is True


def _meet_url(event: dict[str, Any]) -> str | None:
    if event.get("hangoutLink"):
        return str(event["hangoutLink"])
    for entry in event.get("conferenceData", {}).get("entryPoints", []):
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return str(entry["uri"])
    return None


def _meet_code(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else url


def _parse_start(event: dict[str, Any]) -> datetime | None:
    raw = event.get("start", {}).get("dateTime")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _parse_end(event: dict[str, Any]) -> datetime | None:
    raw = event.get("end", {}).get("dateTime")
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)
