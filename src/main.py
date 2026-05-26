import asyncio
import logging
import signal
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import structlog

from src.auth.oauth_user import OAuthUserAuth
from src.auth.token_store import TokenStore
from src.bot.browser_session import BrowserSessionFactory
from src.bot.meeting_session import MeetingSession
from src.bot.session_keepalive import BotSessionKeepAlive
from src.bot.storage_state_store import StorageStateStore
from src.calendar_watcher.client import CalendarClient
from src.calendar_watcher.watcher import CalendarWatcher
from src.config import load_settings
from src.discord_sender.client import DiscordClient
from src.discord_sender.delivery import DiscordDelivery
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
    for noisy_logger in ("httpx", "httpcore", "telegram"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
    )


def _build_result_processor(settings):
    def pipeline() -> GeminiPipeline:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for meeting processing")
        return GeminiPipeline(
            GeminiClient(
                settings.gemini_api_key,
                settings.gemini_model,
                request_timeout_seconds=settings.gemini_request_timeout_seconds,
            ),
            settings.output_dir,
        )

    async def process(result: MeetingResult, generate_documents: bool = False):
        output_paths = await pipeline().process(result, generate_documents=generate_documents)
        if not generate_documents:
            return output_paths
        transcript_path, summary_path, minutes_path, notes_path = output_paths
        if settings.delivery_enabled and settings.discord_bot_token and settings.discord_channel_id:
            discord = DiscordDelivery(DiscordClient(settings.discord_bot_token, settings.discord_channel_id))
            summary = summary_path.read_text()
            await discord.deliver(result, notes_path, summary)
        elif settings.delivery_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
            telegram = TelegramDelivery(TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id))
            summary = summary_path.read_text()
            await telegram.deliver(result, notes_path, summary)
        return transcript_path, summary_path, minutes_path, notes_path

    async def process_many(
        results: tuple[MeetingResult, ...],
        append: bool = True,
        on_progress=None,
        generate_documents: bool = False,
    ):
        output_paths = await pipeline().process_many(
            results,
            append=append,
            on_progress=on_progress,
            generate_documents=generate_documents,
        )
        if not generate_documents:
            return output_paths
        transcript_path, summary_path, minutes_path, notes_path = output_paths
        result = results[-1]
        if settings.delivery_enabled and settings.discord_bot_token and settings.discord_channel_id:
            discord = DiscordDelivery(DiscordClient(settings.discord_bot_token, settings.discord_channel_id))
            summary = summary_path.read_text()
            await discord.deliver(result, notes_path, summary)
        elif settings.delivery_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
            telegram = TelegramDelivery(TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id))
            summary = summary_path.read_text()
            await telegram.deliver(result, notes_path, summary)
        return output_paths

    async def generate_documents(transcript: str, title: str, meet_code: str, admin_instruction: str, on_progress=None):
        return await pipeline().generate_documents(
            transcript,
            title,
            meet_code,
            admin_instruction,
            append=False,
            on_progress=on_progress,
        )

    process.process_many = process_many
    process.generate_documents = generate_documents
    return process


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("meeting_assistant_starting")

    token_store = TokenStore(settings.token_store_path, settings.token_passphrase)
    storage_store = StorageStateStore(settings.storage_state_path, settings.storage_passphrase)
    gemini_client = (
        GeminiClient(
            settings.gemini_api_key,
            settings.gemini_model,
            request_timeout_seconds=settings.gemini_request_timeout_seconds,
        )
        if settings.gemini_api_key
        else None
    )
    telegram_client = (
        TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
        if not settings.discord_bot_token and settings.telegram_bot_token and settings.telegram_chat_id
        else None
    )
    discord_client = (
        DiscordClient(settings.discord_bot_token, settings.discord_channel_id)
        if settings.discord_bot_token and settings.discord_channel_id
        else None
    )
    validation = await validate_startup(
        settings,
        token_store,
        storage_store,
        gemini_client,
        telegram_client,
        discord_client,
    )
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
    browser_factory = BrowserSessionFactory(storage_store, headless=settings.bot_headless)
    keepalive = BotSessionKeepAlive(browser_factory, storage_store, settings.bot_email, settings.bot_password)
    result_processor = _build_result_processor(settings)
    meeting_session = MeetingSession(
        repo,
        browser_factory,
        settings.audio_dir,
        settings.audio_source,
        settings.bot_display_name,
        result_processor,
        settings.auto_purge_audio,
        lambda: repo.get_audio_retention_days(settings.audio_retention_days),
        settings.screenshot_dir,
        settings.screenshot_interval_seconds,
        settings.screenshot_capture_enabled,
    )
    runner = JobRunner(repo, meeting_session.run, settings.max_concurrent_meetings)
    runner.start()
    if settings.bot_session_keepalive_enabled:
        runner.scheduler.add_job(
            keepalive.run,
            "interval",
            seconds=settings.bot_session_keepalive_interval_seconds,
            next_run_time=datetime.now(UTC),
            id="bot-session-keepalive",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    notification_client = (discord_client or telegram_client) if settings.health_notify_enabled else None
    if gemini_client or notification_client:
        daily_check = DailyHealthCheck(notification_client, gemini_client)
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
    command_task = asyncio.create_task(_run_admin_command_loop(settings, repo, runner, result_processor))
    await stop_event.wait()
    watcher_task.cancel()
    command_task.cancel()
    runner.shutdown()
    log.info("meeting_assistant_stopping")


async def _run_admin_command_loop(settings, repo: MeetingsRepo, runner: JobRunner, result_processor) -> None:
    regenerate_tasks: set[asyncio.Task] = set()
    while True:
        for command in repo.claim_pending_rejoins():
            try:
                row = repo.get(command["meet_code"])
                if not row:
                    repo.complete_command(command["id"], "failed", "meeting not found")
                    continue
                meeting = MeetingEvent(
                    meet_code=row["meet_code"],
                    event_id=row["event_id"],
                    start_utc=datetime.now(UTC),
                    end_utc=None,
                    title=row["title"],
                    organizer=None,
                    attendees=(),
                )
                runner.schedule_manual_join(meeting, command["id"])
                repo.complete_command(command["id"])
            except Exception as exc:
                repo.complete_command(command["id"], "failed", str(exc))
        for command in repo.claim_pending_regenerates():
            task = asyncio.create_task(_run_regenerate_command(settings, command, result_processor))
            regenerate_tasks.add(task)
            task.add_done_callback(regenerate_tasks.discard)
        await asyncio.sleep(5)


async def _run_regenerate_command(settings, command, result_processor) -> None:
    repo = MeetingsRepo(connect(settings.db_path))
    meet_code = command["meet_code"]
    try:
        row = repo.get(meet_code)
        if not row:
            repo.complete_command(command["id"], "failed", "meeting not found")
            return
        if not str(row["admin_instruction"] or "").strip():
            repo.complete_command(command["id"], "failed", "admin instruction is required")
            repo.mark_processing(meet_code, "failed", 0, 0, "admin instruction is required", stage="failed")
            return
        repo.mark_processing(meet_code, "running", 0, 3, stage="preparing")
        participants = _participants(row)
        instruction = str(row["admin_instruction"] or "")
        async def on_progress(stage: str, batch: int, total: int) -> None:
            repo.mark_processing(meet_code, "running", batch, total, stage=stage)

        transcript_path, transcript = _existing_transcript(settings.output_dir, row)
        if not transcript:
            audio_paths = _audio_paths(settings.audio_dir, meet_code)
            if not audio_paths:
                repo.complete_command(command["id"], "failed", "no transcript or audio files found")
                repo.mark_processing(meet_code, "failed", 0, 0, "no transcript or audio files found", stage="failed")
                return
            results = []
            for audio_path in audio_paths:
                results.append(
                    MeetingResult(
                        meet_code=meet_code,
                        audio_path=audio_path,
                        duration_sec=_duration_seconds(audio_path),
                        exit_reason="regenerate",
                        participant_names=participants,
                        title=row["title"] or meet_code,
                        actual_end_utc=_parse_dt(row["actual_end_utc"]),
                        admin_instruction=instruction,
                    )
                )
            transcript_only = await result_processor.process_many(
                tuple(results),
                append=False,
                on_progress=on_progress,
                generate_documents=False,
            )
            transcript_path = transcript_only[0]
            transcript = transcript_path.read_text(encoding="utf-8")
        summary_path, minutes_path, notes_path = await result_processor.generate_documents(
            transcript,
            row["title"] or meet_code,
            meet_code,
            instruction,
            on_progress=on_progress,
        )
        repo.mark_processing(meet_code, "done", 3, 3, stage="done")
        repo.mark_delivered(
            meet_code,
            str(notes_path),
            transcript_path=str(transcript_path),
            summary_path=str(summary_path),
            minutes_path=str(minutes_path),
        )
        repo.complete_command(command["id"])
    except Exception as exc:
        repo.mark_processing(meet_code, "failed", 0, 0, str(exc), stage="failed")
        repo.complete_command(command["id"], "failed", str(exc))
    finally:
        repo.conn.close()


def _participants(row) -> tuple[str, ...]:
    names = []
    if row["organizer"]:
        names.append(row["organizer"])
    if row["attendees"]:
        try:
            names.extend(json.loads(row["attendees"]))
        except json.JSONDecodeError:
            pass
    return tuple(dict.fromkeys(str(name) for name in names if name))


def _audio_paths(audio_dir: Path, meet_code: str) -> list[Path]:
    if not audio_dir.exists():
        return []
    return sorted(
        (path for path in audio_dir.glob(f"{meet_code}*.opus") if path.stat().st_size > 0),
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def _output_paths(output_dir: Path, title: str) -> tuple[Path, Path, Path, Path]:
    from src.gemini.pipeline import _slug

    slug = _slug(title)
    return (
        output_dir / f"transcript-{slug}.md",
        output_dir / f"summary-{slug}.md",
        output_dir / f"meeting-minutes-{slug}.md",
        output_dir / f"meeting-notes-{slug}.md",
    )


def _existing_transcript(output_dir: Path, row) -> tuple[Path | None, str]:
    if row["transcript_path"]:
        path = Path(row["transcript_path"])
        if path.exists():
            return path, path.read_text(encoding="utf-8")
    transcript_path = _output_paths(output_dir, row["title"] or row["meet_code"])[0]
    if transcript_path.exists():
        return transcript_path, transcript_path.read_text(encoding="utf-8")
    return None, ""


def _duration_seconds(path: Path) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        return max(1, int(float(result.stdout.strip())))
    except (TypeError, ValueError):
        return 0


def _parse_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


if __name__ == "__main__":
    asyncio.run(main())
