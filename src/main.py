import asyncio
import logging
import signal

import structlog

from src.auth.oauth_user import OAuthUserAuth
from src.auth.token_store import TokenStore
from src.calendar_watcher.client import CalendarClient
from src.calendar_watcher.watcher import CalendarWatcher
from src.config import load_settings
from src.models.meeting_event import MeetingEvent


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
    )


async def log_meeting(meeting: MeetingEvent) -> None:
    structlog.get_logger(__name__).info(
        "qualifying_meeting_detected",
        meet_code=meeting.meet_code,
        event_id=meeting.event_id,
        start_utc=meeting.start_utc.isoformat(),
        title=meeting.title,
    )


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("meeting_assistant_starting")

    token_store = TokenStore(settings.token_store_path, settings.token_passphrase)
    auth = OAuthUserAuth(
        token_store,
        str(settings.google_oauth_client_secrets),
        settings.oauth_redirect_port,
    )
    credentials = auth.get_credentials()
    calendar_client = CalendarClient(credentials, settings.calendar_id)
    watcher = CalendarWatcher(
        calendar_client,
        settings.user_email,
        log_meeting,
        settings.calendar_poll_interval_seconds,
        settings.calendar_lookahead_minutes,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    watcher_task = asyncio.create_task(watcher.run_forever())
    await stop_event.wait()
    watcher_task.cancel()
    log.info("meeting_assistant_stopping")


if __name__ == "__main__":
    asyncio.run(main())
