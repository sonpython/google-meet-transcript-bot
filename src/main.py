import asyncio
import logging
import signal

import structlog

from src.auth.oauth_user import OAuthUserAuth
from src.auth.token_store import TokenStore
from src.bot.browser_session import BrowserSessionFactory
from src.bot.meeting_session import MeetingSession
from src.bot.storage_state_store import StorageStateStore
from src.calendar_watcher.client import CalendarClient
from src.calendar_watcher.watcher import CalendarWatcher
from src.config import load_settings
from src.gemini.client import GeminiClient
from src.gemini.pipeline import GeminiPipeline
from src.health.daily_check import DailyHealthCheck, next_health_check_time
from src.health.startup_validation import validate_startup
from src.models.meeting_event import MeetingEvent
from src.models.meeting_result import MeetingResult
from src.scheduler.job_runner import JobRunner
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo
from src.telegram_sender.client import TelegramClient
from src.telegram_sender.delivery import TelegramDelivery


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


def _build_result_processor(settings):
    async def process(result: MeetingResult):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for meeting processing")
        gemini = GeminiPipeline(GeminiClient(settings.gemini_api_key, settings.gemini_model), settings.output_dir)
        transcript_path, summary_path, notes_path = await gemini.process(result)
        if settings.telegram_bot_token and settings.telegram_chat_id:
            telegram = TelegramDelivery(TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id))
            summary = summary_path.read_text()
            await telegram.deliver(result, notes_path, summary)
        return notes_path

    return process


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("meeting_assistant_starting")

    token_store = TokenStore(settings.token_store_path, settings.token_passphrase)
    storage_store = StorageStateStore(settings.storage_state_path, settings.storage_passphrase)
    gemini_client = GeminiClient(settings.gemini_api_key, settings.gemini_model) if settings.gemini_api_key else None
    telegram_client = (
        TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
        if settings.telegram_bot_token and settings.telegram_chat_id
        else None
    )
    validation = await validate_startup(settings, token_store, storage_store, gemini_client, telegram_client)
    if not validation.ok:
        log.warning("startup_validation_failed", failures=validation.failures)
    auth = OAuthUserAuth(
        token_store,
        str(settings.google_oauth_client_secrets),
        settings.oauth_redirect_port,
    )
    credentials = auth.get_credentials()
    calendar_client = CalendarClient(credentials, settings.calendar_id)
    repo = MeetingsRepo(connect(settings.db_path))
    browser_factory = BrowserSessionFactory(storage_store)
    meeting_session = MeetingSession(
        repo,
        browser_factory,
        settings.audio_dir,
        settings.bot_display_name,
        _build_result_processor(settings),
        settings.auto_purge_audio,
    )
    runner = JobRunner(repo, meeting_session.run)
    runner.start()
    if gemini_client or telegram_client:
        daily_check = DailyHealthCheck(telegram_client, gemini_client)
        runner.scheduler.add_job(
            daily_check.run,
            "interval",
            days=1,
            next_run_time=next_health_check_time(),
            id="daily-health-check",
            replace_existing=True,
        )
    watcher = CalendarWatcher(
        calendar_client,
        settings.user_email,
        runner.schedule_bot_join,
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
    runner.shutdown()
    log.info("meeting_assistant_stopping")


if __name__ == "__main__":
    asyncio.run(main())
