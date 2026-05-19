import os
from pathlib import Path

import structlog

from src.bot.audio_recorder import AudioRecorder
from src.bot.meet_joiner import MeetJoiner
from src.bot.meet_monitor import MeetMonitor
from src.models.meeting_event import MeetingEvent
from src.models.meeting_result import MeetingResult


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
    ) -> None:
        self.repo = repo
        self.browser_factory = browser_factory
        self.audio_dir = audio_dir
        self.audio_source = audio_source
        self.display_name = display_name
        self.process_result = process_result
        self.auto_purge_audio = auto_purge_audio
        self.log = structlog.get_logger(__name__)

    async def run(self, meeting: MeetingEvent) -> None:
        session = None
        recorder = AudioRecorder(self.audio_dir, self.audio_source)
        audio_path = None
        try:
            self.repo.mark_status(meeting.meet_code, "joining")
            session = await self.browser_factory.launch_with_state()
            join_result = await MeetJoiner().join(session.page, meeting.meet_code, self.display_name)
            if not join_result.admitted:
                self.repo.mark_status(meeting.meet_code, "failed", join_result.error_msg or join_result.status)
                return
            audio_path = recorder.start(meeting.meet_code)
            self.repo.mark_status(meeting.meet_code, "recording", audio_path=str(audio_path))
            reason, participants, duration = await MeetMonitor(session.page).run_until_exit()
            final_path = recorder.stop()
            if reason == "no_one_joined":
                self.repo.mark_status(meeting.meet_code, "no_one_joined", None, audio_path=str(final_path))
                if self.auto_purge_audio:
                    os.remove(final_path)
                return
            result = MeetingResult(
                meeting.meet_code,
                final_path,
                duration,
                reason,
                participants,
                meeting.title,
            )
            self.repo.mark_status(meeting.meet_code, "processing", audio_path=str(final_path))
            output_paths = await self.process_result(result)
            notes_path, extra_paths = _normalize_output_paths(output_paths)
            self.repo.mark_delivered(meeting.meet_code, str(notes_path), **extra_paths)
            if self.auto_purge_audio:
                os.remove(final_path)
        except Exception as exc:
            self.log.exception("meeting_session_failed", meet_code=meeting.meet_code)
            if recorder.is_running():
                audio_path = recorder.stop()
            self.repo.mark_status(meeting.meet_code, "failed", str(exc), audio_path=str(audio_path) if audio_path else None)
        finally:
            if session:
                await session.close()


def _normalize_output_paths(output_paths) -> tuple[Path, dict[str, str]]:
    if isinstance(output_paths, tuple):
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
