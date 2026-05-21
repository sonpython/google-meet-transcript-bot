from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MeetingResult:
    meet_code: str
    audio_path: Path
    duration_sec: int
    exit_reason: str
    participant_names: tuple[str, ...]
    title: str = ""
    actual_end_utc: datetime | None = None
    admin_instruction: str = ""
