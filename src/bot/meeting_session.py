import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from src.bot.audio_recorder import AudioRecorder
from src.bot.meet_joiner import MeetJoiner
from src.bot.meet_monitor import MeetMonitor
from src.models.meeting_event import MeetingEvent
from src.models.meeting_result import MeetingResult
from src.runtime_audio import create_session_sink, remove_session_sink, safe_session_sink_name

AUTO_REJOIN_EXIT_REASONS = {"page_closed"}
AUTO_REJOIN_JOIN_STATUSES = {"network_error", "timeout"}
NON_RETRYABLE_JOIN_STATUSES = {"signed_out"}
CONFIRMED_MEETING_END_REASONS = {"alone", "force_out", "ended", "hard_cap"}
MAX_AUTO_REJOINS = 2
AUTO_REJOIN_DELAY_SECONDS = 10


class MeetingSession:
    def __init__(
        self,
        repo,
        browser_factory,
        audio_dir: Path,
        audio_source: str,
        display_name: str,
        process_result,
        auto_purge_audio: bool = True,
        audio_retention_days: int | Callable[[], int] = 10,
    ) -> None:
        self.repo = repo
        self.browser_factory = browser_factory
        self.audio_dir = audio_dir
        self.audio_source = audio_source
        self.display_name = display_name
        self.process_result = process_result
        self.auto_purge_audio = auto_purge_audio
        self.audio_retention_days = audio_retention_days
        self.log = structlog.get_logger(__name__)
        self._processing_tasks: set[asyncio.Task] = set()
        self._processing_locks: dict[str, asyncio.Lock] = {}

    async def run(self, meeting: MeetingEvent) -> None:
        recorded_paths: list[Path] = []
        recorded_durations: list[int] = []
        total_duration = 0
        all_participants: list[str] = []
        final_reason = "unknown"
        actual_end = meeting.start_utc
        for attempt in range(MAX_AUTO_REJOINS + 1):
            session = None
            recorder = AudioRecorder(self.audio_dir, self.audio_source)
            audio_path = None
            sink_name = None
            monitor_source = self.audio_source
            try:
                self.repo.mark_status(meeting.meet_code, "joining")
                sink_name = safe_session_sink_name(meeting.meet_code)
                monitor_source = create_session_sink(sink_name)
                self.log.info(
                    "meeting_session_audio_sink_created",
                    meet_code=meeting.meet_code,
                    sink=sink_name,
                    monitor=monitor_source,
                    attempt=attempt + 1,
                )
                session = await self.browser_factory.launch_with_state(pulse_sink=sink_name)
                join_result = await MeetJoiner().join(session.page, meeting.meet_code, self.display_name)
                if not join_result.admitted:
                    error = join_result.error_msg or join_result.status
                    if join_result.status in NON_RETRYABLE_JOIN_STATUSES:
                        self.repo.mark_status(meeting.meet_code, "failed", error)
                        return
                    if self._should_auto_rejoin_join(join_result.status, attempt, meeting):
                        await self._pause_before_auto_rejoin(meeting.meet_code, error)
                        continue
                    self.repo.mark_status(meeting.meet_code, "failed", error)
                    return
                audio_path = recorder.start(meeting.meet_code, audio_source=monitor_source)
                self.repo.mark_status(meeting.meet_code, "recording", audio_path=str(audio_path))
                reason, participants, duration, actual_end = await MeetMonitor(
                    session.page,
                    should_force_exit=lambda: self._claim_force_out(meeting.meet_code),
                ).run_until_exit()
                final_path = recorder.stop()
                recorded_paths.append(final_path)
                recorded_durations.append(duration)
                total_duration += duration
                all_participants.extend(str(item) for item in participants)
                final_reason = reason
                if reason == "no_one_joined":
                    self.repo.mark_status(
                        meeting.meet_code,
                        "no_one_joined",
                        None,
                        audio_path=str(final_path),
                        actual_end_utc=meeting.start_utc.isoformat(),
                        meeting_end_confirmed=1,
                        meeting_end_reason=reason,
                    )
                    self._cleanup_audio()
                    return
                if self._should_auto_rejoin_exit(reason, attempt, meeting):
                    await self._pause_before_auto_rejoin(meeting.meet_code, reason)
                    continue
                break
            except Exception as exc:
                self.log.exception("meeting_session_failed", meet_code=meeting.meet_code, attempt=attempt + 1)
                if recorder.is_running():
                    try:
                        audio_path = recorder.stop()
                        recorded_paths.append(audio_path)
                        recorded_durations.append(0)
                    except Exception:
                        self.log.exception("meeting_session_recorder_stop_failed", meet_code=meeting.meet_code)
                if self._should_auto_rejoin_exception(attempt, meeting):
                    await self._pause_before_auto_rejoin(meeting.meet_code, str(exc))
                    continue
                self.repo.mark_status(
                    meeting.meet_code,
                    "failed",
                    str(exc),
                    audio_path=str(audio_path) if audio_path else None,
                )
                return
            finally:
                if session:
                    await session.close()
                if sink_name:
                    remove_session_sink(sink_name)
                    self.log.info("meeting_session_audio_sink_removed", meet_code=meeting.meet_code, sink=sink_name)
        if not recorded_paths:
            self.repo.mark_status(meeting.meet_code, "failed", "no audio recorded")
            return
        meeting_end_confirmed = final_reason in CONFIRMED_MEETING_END_REASONS
        self.repo.mark_status(
            meeting.meet_code,
            "recorded",
            None if meeting_end_confirmed else f"meeting end not confirmed: {final_reason}",
            audio_path=str(recorded_paths[-1]),
            actual_end_utc=actual_end.isoformat(),
            meeting_end_confirmed=1 if meeting_end_confirmed else 0,
            meeting_end_reason=final_reason,
        )
        if not meeting_end_confirmed:
            self.log.warning(
                "meeting_session_processing_skipped_unconfirmed_end",
                meet_code=meeting.meet_code,
                reason=final_reason,
            )
            return
        self._start_processing_task(
            meeting,
            recorded_paths,
            recorded_durations,
            total_duration,
            final_reason,
            tuple(dict.fromkeys(all_participants)),
            actual_end,
        )

    def _claim_force_out(self, meet_code: str) -> bool:
        command = self.repo.claim_pending_force_out(meet_code)
        if not command:
            return False
        self.repo.complete_command(command["id"], "done")
        return True

    def _should_auto_rejoin_join(self, status: str, attempt: int, meeting: MeetingEvent) -> bool:
        return status in AUTO_REJOIN_JOIN_STATUSES and self._can_auto_rejoin(attempt, meeting)

    def _should_auto_rejoin_exit(self, reason: str, attempt: int, meeting: MeetingEvent) -> bool:
        return reason in AUTO_REJOIN_EXIT_REASONS and self._can_auto_rejoin(attempt, meeting)

    def _should_auto_rejoin_exception(self, attempt: int, meeting: MeetingEvent) -> bool:
        return self._can_auto_rejoin(attempt, meeting)

    def _can_auto_rejoin(self, attempt: int, meeting: MeetingEvent) -> bool:
        return attempt < MAX_AUTO_REJOINS

    async def _pause_before_auto_rejoin(self, meet_code: str, reason: str) -> None:
        self.log.warning("meeting_session_auto_rejoin", meet_code=meet_code, reason=reason)
        self.repo.mark_status(meet_code, "joining", f"auto rejoin: {reason}")
        await asyncio.sleep(AUTO_REJOIN_DELAY_SECONDS)

    def _start_processing_task(
        self,
        meeting: MeetingEvent,
        recorded_paths: list[Path],
        recorded_durations: list[int],
        total_duration: int,
        final_reason: str,
        participant_names: tuple[str, ...],
        actual_end: datetime,
    ) -> None:
        task = asyncio.create_task(
            self._process_recordings(
                meeting,
                recorded_paths,
                recorded_durations,
                total_duration,
                final_reason,
                participant_names,
                actual_end,
            )
        )
        self._processing_tasks.add(task)
        task.add_done_callback(self._processing_tasks.discard)

    async def _process_recordings(
        self,
        meeting: MeetingEvent,
        recorded_paths: list[Path],
        recorded_durations: list[int],
        total_duration: int,
        final_reason: str,
        participant_names: tuple[str, ...],
        actual_end: datetime,
    ) -> None:
        lock = self._processing_locks.setdefault(meeting.meet_code, asyncio.Lock())
        async with lock:
            total = len(recorded_paths)
            output_paths = None
            current_batch = 0
            try:
                self.repo.mark_processing(meeting.meet_code, "running", 0, total)
                admin_instruction = self._admin_instruction(meeting.meet_code)
                results = []
                for index, path in enumerate(recorded_paths, start=1):
                    duration = recorded_durations[index - 1] if index - 1 < len(recorded_durations) else 0
                    results.append(
                        MeetingResult(
                        meeting.meet_code,
                        path,
                        duration,
                        final_reason,
                        participant_names,
                        meeting.title,
                        actual_end,
                        admin_instruction,
                    )
                    )
                if hasattr(self.process_result, "process_many"):
                    async def on_progress(stage: str, batch: int, progress_total: int) -> None:
                        nonlocal current_batch
                        current_batch = batch
                        self.repo.mark_processing(
                            meeting.meet_code,
                            "running",
                            batch,
                            progress_total,
                            stage=stage,
                        )

                    output_paths = await self.process_result.process_many(
                        tuple(results),
                        on_progress=on_progress,
                    )
                else:
                    for index, result in enumerate(results, start=1):
                        current_batch = index
                        self.repo.mark_processing(meeting.meet_code, "running", index, total)
                        output_paths = await self.process_result(result)
                if not output_paths:
                    raise RuntimeError("no output generated")
                notes_path, extra_paths = _normalize_output_paths(output_paths)
                self.repo.mark_processing(meeting.meet_code, "done", total, total, stage="done")
                self.repo.mark_delivered(meeting.meet_code, str(notes_path), **extra_paths)
                self._cleanup_audio()
            except Exception as exc:
                self.log.exception("meeting_session_processing_failed", meet_code=meeting.meet_code)
                self.repo.mark_processing(
                    meeting.meet_code,
                    "failed",
                    current_batch,
                    total,
                    str(exc),
                )
                self.repo.mark_status(meeting.meet_code, "recorded", f"processing failed: {exc}")

    def _admin_instruction(self, meet_code: str) -> str:
        row = self.repo.get(meet_code)
        if not row:
            return ""
        return str(row["admin_instruction"] or "") if "admin_instruction" in row.keys() else ""

    async def wait_for_processing(self) -> None:
        if self._processing_tasks:
            await asyncio.gather(*tuple(self._processing_tasks))

    def _retention_days(self) -> int:
        if callable(self.audio_retention_days):
            return max(0, int(self.audio_retention_days()))
        return max(0, int(self.audio_retention_days))

    def _cleanup_audio(self) -> None:
        days = self._retention_days()
        if days <= 0:
            cutoff = datetime.now(UTC)
        else:
            cutoff = datetime.now(UTC) - timedelta(days=days)
        if not self.audio_dir.exists():
            return
        for path in self.audio_dir.glob("*.opus"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if days <= 0 or modified < cutoff:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass


def _normalize_output_paths(output_paths) -> tuple[Path, dict[str, str]]:
    if isinstance(output_paths, tuple):
        if len(output_paths) == 1:
            transcript_path = output_paths[0]
            return transcript_path, {"transcript_path": str(transcript_path)}
        if len(output_paths) == 4:
            transcript_path, summary_path, minutes_path, notes_path = output_paths
            return notes_path, {
                "transcript_path": str(transcript_path),
                "summary_path": str(summary_path),
                "minutes_path": str(minutes_path),
            }
        transcript_path, summary_path, notes_path = output_paths
        return notes_path, {
            "transcript_path": str(transcript_path),
            "summary_path": str(summary_path),
        }
    return output_paths, {}
