from datetime import UTC, datetime

from src.calendar_watcher.classifier import is_qualifying, to_meeting_event


USER_EMAIL = "user@your-domain.com"


def event(**overrides):
    base = {
        "id": "event-1",
        "summary": "Planning",
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
        "start": {"dateTime": "2026-05-20T10:00:00Z"},
        "organizer": {"email": "host@your-domain.com"},
        "attendees": [{"email": USER_EMAIL, "responseStatus": "accepted"}],
    }
    base.update(overrides)
    return base


def test_organizer_with_meet_link_qualifies():
    candidate = event(organizer={"email": USER_EMAIL}, attendees=[])
    assert is_qualifying(candidate, USER_EMAIL)


def test_attendee_not_declined_qualifies_and_maps_event():
    meeting = to_meeting_event(event(), USER_EMAIL)
    assert meeting is not None
    assert meeting.meet_code == "abc-defg-hij"
    assert meeting.event_id == "event-1"
    assert meeting.start_utc == datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    assert meeting.attendees == (USER_EMAIL,)


def test_declined_attendee_is_skipped():
    candidate = event(attendees=[{"email": USER_EMAIL, "responseStatus": "declined"}])
    assert not is_qualifying(candidate, USER_EMAIL)


def test_event_without_meet_link_is_skipped():
    candidate = event(hangoutLink=None, conferenceData={})
    assert not is_qualifying(candidate, USER_EMAIL)


def test_external_event_without_user_is_skipped():
    candidate = event(attendees=[{"email": "someone@else.com", "responseStatus": "accepted"}])
    assert not is_qualifying(candidate, USER_EMAIL)


def test_conference_data_video_entry_is_supported():
    candidate = event(
        hangoutLink=None,
        conferenceData={
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+100000000"},
                {"entryPointType": "video", "uri": "https://meet.google.com/xyz-abcd-efg"},
            ]
        },
    )
    meeting = to_meeting_event(candidate, USER_EMAIL)
    assert meeting is not None
    assert meeting.meet_code == "xyz-abcd-efg"
