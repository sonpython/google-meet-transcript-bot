# Phase 04 - Calendar bot-invite switch

## Context Links

- Design: brainstorm Phase B and decisions D1, D6
- Classifier: `src/calendar_watcher/classifier.py:8` (`is_qualifying`), `:23` (`to_meeting_event`)
- Callers: `src/calendar_watcher/watcher.py:32`, `src/health_server.py:701`, `src/health_server.py:951`
- Watcher construction: `src/main.py:198-203` passes `settings.user_email`
- Config: `src/config.py:10` (`user_email`), `src/config.py:30` (`bot_email`)
- Tests: `tests/test_calendar_classifier.py`
- OAuth bootstrap script: `scripts/calendar_first_login.py`, token at `TOKEN_STORE_PATH` (`src/config.py:12`)

## Overview

- Priority: P1
- Status: done
- Effort: 1.5h code, plus a one-time OAuth re-run on the host
- The watched calendar becomes the bot's own calendar, and any invited meeting with a Meet link qualifies unless the bot declined it.

## Key Insights

- The OAuth token decides whose calendar is read. `CalendarClient` is built from `OAuthUserAuth` credentials (`src/health_server.py:694-696`, same pattern in `src/main.py`), so the switch is an operations step: re-run the calendar OAuth signed in as `BOT_EMAIL` and replace `TOKEN_STORE_PATH`. No client code selects the calendar owner beyond `calendar_id="primary"` (`src/config.py:16`).
- The classifier keeps its two-argument signature. Only the argument value changes from `settings.user_email` to `settings.bot_email` at three call sites. Renaming the parameter to `watched_email` documents the new meaning without breaking positional callers.
- Google marks the credential owner with `"self": true`, already handled at `src/calendar_watcher/classifier.py:57`. On the bot's own calendar this means the current logic would already qualify most events; the deliberate change is dropping the membership requirement so an invite alone is enough (D6).
- `tests/test_calendar_classifier.py:56` asserts that an event without the watched user is skipped. Under D6 that expectation inverts. This is an intended behavior change, so the test is rewritten to assert the new rule, not deleted.

## Requirements

Functional:
- An event qualifies when it has a Meet link and the watched account has not declined it.
- An event without a Meet link never qualifies.
- A declined event never qualifies.
- `USER_EMAIL` is no longer used for join gating. It stays as the seed for the first admin row and as the default attendee filter value.

Non-functional:
- No new config field. `BOT_EMAIL` already exists at `src/config.py:30`.
- Cutover is clean, with no dual-calendar period, per the design.

## Architecture

Before:

```
USER_EMAIL calendar -> qualifies if USER_EMAIL is organizer or a non-declined attendee -> join
```

After:

```
BOT_EMAIL calendar -> qualifies if the event has a Meet link and the bot entry is not "declined" -> join
```

New classifier rule:

```python
def is_qualifying(event, watched_email) -> bool:
    if not _meet_url(event):
        return False
    entry = _watched_entry(event, watched_email)   # self flag first, then email match, attendees then organizer
    if entry and entry.get("responseStatus") == "declined":
        return False
    return True
```

`_watched_entry` returns the attendee dict whose `self` is true or whose email matches `watched_email`, else the organizer dict under the same test, else `None`. `None` means the event sits on the watched calendar without an explicit attendee record, which still qualifies under D6.

## Related Code Files

Modify:
- `src/calendar_watcher/classifier.py` - rewrite `is_qualifying`, rename the parameter in both functions to `watched_email`, add `_watched_entry`.
- `src/main.py:200` - pass `settings.bot_email`.
- `src/health_server.py:701` and `:951` - pass `settings.bot_email`.
- `tests/test_calendar_classifier.py` - rewrite the membership expectations, keep the Meet link and declined cases.
- `src/calendar_watcher/watcher.py` - rename the attribute and constructor parameter to `watched_email` for clarity. Positional construction in `src/main.py` is unaffected.

No file is deleted. No config field is added.

## Implementation Steps

1. Rewrite `is_qualifying` in `src/calendar_watcher/classifier.py` per the rule above. Keep `_meet_url`, `_meet_code`, `_parse_start`, `_parse_end`, `_raw_email`, `_is_self` unchanged.
2. Rename `user_email` to `watched_email` in `is_qualifying` and `to_meeting_event`.
3. Rename `user_email` to `watched_email` in `src/calendar_watcher/watcher.py:17,23,32`.
4. Change the three call sites to `settings.bot_email`.
5. Update `tests/test_calendar_classifier.py`:
   - Keep: organizer qualifies, self attendee qualifies, declined is skipped, no Meet link is skipped, conferenceData video entry is supported, event mapping fields.
   - Rewrite `test_external_event_without_user_is_skipped` into `test_event_on_watched_calendar_without_bot_entry_still_qualifies`, with a comment stating the invite-driven rule.
   - Add: bot listed as `needsAction` qualifies, bot listed as `tentative` qualifies, bot listed as `declined` is skipped, all-day event without `dateTime` maps to `None` from `to_meeting_event`.
6. Run `uv run pytest` and `uv run python -m compileall src tests`.
7. Operations, done at deploy time and documented in phase 06:
   - Back up the current token: `cp /opt/meeting-assistant/data/tokens/user-token.fernet{,.bak-YYMMDD}`.
   - Re-run `scripts/calendar_first_login.py` signed in as `BOT_EMAIL`, writing a fresh `TOKEN_STORE_PATH`.
   - Restart the container and check `/admin` upcoming events for the bot's invitations.

## Todo List

- [x] Rewrite `is_qualifying` with the invite rule
- [x] Rename the parameter to `watched_email` in the classifier and the watcher
- [x] Three call sites pass `settings.bot_email`
- [x] Rewrite and extend `tests/test_calendar_classifier.py`
- [x] Full test suite green
- [ ] Runbook step for the OAuth re-run written for phase 06

## Test Matrix

| Level | Case | Expectation |
|-------|------|-------------|
| Unit | bot is an accepted attendee | qualifies |
| Unit | bot is `needsAction` | qualifies |
| Unit | bot is `tentative` | qualifies |
| Unit | bot is `declined` | skipped |
| Unit | bot is the organizer, no attendees | qualifies |
| Unit | event on the calendar with no bot entry at all | qualifies, invite-driven rule |
| Unit | no Meet link and empty conferenceData | skipped |
| Unit | conferenceData video entry only | qualifies, correct meet code |
| Unit | all-day event, no `start.dateTime` | `to_meeting_event` returns None |
| Unit | attendee emails are mapped onto the event | tuple matches the calendar payload |
| Integration | `CalendarWatcher.poll_once` with a stub client over a mixed event list | only qualifying events reach the handler, count matches |

## Success Criteria

- The bot joins a meeting purely because `BOT_EMAIL` was invited, with no code change per user.
- A meeting the bot declined is never scheduled.
- `uv run pytest` green with the rewritten classifier tests.
- After the OAuth re-run, `/admin` upcoming events lists the bot's invitations.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Meetings where the bot is not invited stop being recorded | High | Med | Expected per the design. Announce the cutover to the team and verify during the first week |
| Bot calendar auto-fills with spam invites and the bot joins junk | Low | Med | D6 accepts this for a trusted domain. Decline on the bot calendar removes an event from scope |
| OAuth re-run performed with the wrong account | Med | High | Verify the account on the consent screen, check `/admin` upcoming events right after the restart, keep the token backup |
| Personal blocks on the bot calendar that carry a Meet link get joined | Low | Low | Decline or strip the Meet link on those events |
| Invitations do not appear until manually accepted | Med | Med | Check the Workspace calendar setting for automatic invitation adding during the pilot, listed as an open question |

## Security Considerations

- The calendar OAuth token now belongs to the bot account, which reduces blast radius: it can no longer read the human owner's private calendar.
- Token file permissions and encryption are unchanged, it is still the Fernet store at `TOKEN_STORE_PATH`.
- Anyone in the domain can now cause a recording by inviting the bot. That is the intended trust model under D6 and should be stated in the announcement.

## Rollback

Restore the token backup, revert the commit, restart. The previous calendar and the previous qualifying rule return together, so the two must be rolled back as a pair.

## Next Steps

Phase 06 carries the OAuth re-run into the deployment runbook and the README runtime flow section.
