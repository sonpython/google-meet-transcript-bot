from datetime import UTC, datetime

from src.calendar_watcher.classifier import is_qualifying, to_meeting_event


BOT_EMAIL = "bot@your-domain.com"


def event(**overrides):
    base = {
        "id": "event-1",
        "summary": "Planning",
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
        "start": {"dateTime": "2026-05-20T10:00:00Z"},
        "organizer": {"email": "host@your-domain.com"},
        "attendees": [{"email": BOT_EMAIL, "responseStatus": "accepted"}],
    }
    base.update(overrides)
    return base


def test_organizer_with_meet_link_qualifies():
    candidate = event(organizer={"email": BOT_EMAIL}, attendees=[])
    assert is_qualifying(candidate, BOT_EMAIL)


def test_google_self_organizer_qualifies_even_when_email_setting_differs():
    candidate = event(organizer={"email": "michael@chtlab.io", "self": True}, attendees=[])
    assert is_qualifying(candidate, "sonunix@gmail.com")


def test_google_self_attendee_qualifies_even_when_email_setting_differs():
    candidate = event(attendees=[{"email": "michael@chtlab.io", "self": True, "responseStatus": "needsAction"}])
    assert is_qualifying(candidate, "sonunix@gmail.com")


def test_accepted_attendee_qualifies_and_maps_event():
    meeting = to_meeting_event(event(), BOT_EMAIL)
    assert meeting is not None
    assert meeting.meet_code == "abc-defg-hij"
    assert meeting.event_id == "event-1"
    assert meeting.start_utc == datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    assert meeting.attendees == (BOT_EMAIL,)


def test_needs_action_and_tentative_qualify():
    for status in ("needsAction", "tentative"):
        candidate = event(attendees=[{"email": BOT_EMAIL, "responseStatus": status}])
        assert is_qualifying(candidate, BOT_EMAIL), status


def test_declined_attendee_is_skipped():
    candidate = event(attendees=[{"email": BOT_EMAIL, "responseStatus": "declined"}])
    assert not is_qualifying(candidate, BOT_EMAIL)


def test_declined_self_entry_is_skipped():
    candidate = event(attendees=[{"email": "alias@your-domain.com", "self": True, "responseStatus": "declined"}])
    assert not is_qualifying(candidate, BOT_EMAIL)


def test_event_without_meet_link_is_skipped():
    candidate = event(hangoutLink=None, conferenceData={})
    assert not is_qualifying(candidate, BOT_EMAIL)


def test_event_on_watched_calendar_without_bot_entry_still_qualifies():
    # Invite-driven rule: the watched calendar is the bot's own, so any event
    # sitting on it with a Meet link qualifies even when the attendee list
    # carries no explicit entry for the bot.
    candidate = event(attendees=[{"email": "someone@else.com", "responseStatus": "accepted"}])
    assert is_qualifying(candidate, BOT_EMAIL)


def test_all_day_event_without_datetime_maps_to_none():
    candidate = event(start={"date": "2026-05-20"})
    assert to_meeting_event(candidate, BOT_EMAIL) is None


def test_attendee_emails_are_mapped_onto_the_event():
    candidate = event(
        attendees=[
            {"email": BOT_EMAIL, "responseStatus": "accepted"},
            {"email": "alice@your-domain.com", "responseStatus": "needsAction"},
        ]
    )
    meeting = to_meeting_event(candidate, BOT_EMAIL)
    assert meeting.attendees == (BOT_EMAIL, "alice@your-domain.com")


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
    meeting = to_meeting_event(candidate, BOT_EMAIL)
    assert meeting is not None
    assert meeting.meet_code == "xyz-abcd-efg"
