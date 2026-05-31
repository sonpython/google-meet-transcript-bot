import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrimResult:
    audio_path: Path
    duration_seconds: int
    trimmed: bool
    reason: str = ""


def trim_trailing_silence_after_participants_left(
    audio_path: Path,
    keep_seconds: int,
    original_duration_seconds: int,
    ffmpeg_bin: str = "ffmpeg",
    silence_threshold_db: float = -45.0,
    min_tail_seconds: int = 30,
) -> TrimResult:
    keep_seconds = max(0, int(keep_seconds))
    original_duration_seconds = max(0, int(original_duration_seconds))
    tail_seconds = original_duration_seconds - keep_seconds
    if keep_seconds <= 0:
        return TrimResult(audio_path, original_duration_seconds, False, "invalid_keep_seconds")
    if tail_seconds < min_tail_seconds:
        return TrimResult(audio_path, original_duration_seconds, False, "tail_too_short")
    if not _tail_is_silent(
        audio_path,
        keep_seconds,
        tail_seconds,
        ffmpeg_bin=ffmpeg_bin,
        silence_threshold_db=silence_threshold_db,
    ):
        return TrimResult(audio_path, original_duration_seconds, False, "tail_not_silent")

    output_path = _trimmed_path(audio_path)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-t",
        str(keep_seconds),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        return TrimResult(audio_path, original_duration_seconds, False, "trim_failed")
    return TrimResult(output_path, keep_seconds, True, "tail_silent")


def _tail_is_silent(
    audio_path: Path,
    start_seconds: int,
    duration_seconds: int,
    ffmpeg_bin: str,
    silence_threshold_db: float,
) -> bool:
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostats",
        "-ss",
        str(start_seconds),
        "-t",
        str(duration_seconds),
        "-i",
        str(audio_path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False
    max_volume = _parse_max_volume(result.stderr)
    if max_volume is None:
        return False
    return max_volume <= silence_threshold_db


def _parse_max_volume(stderr: str) -> float | None:
    match = re.search(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB", stderr)
    if not match:
        return None
    value = match.group(1)
    if value == "-inf":
        return float("-inf")
    return float(value)


def _trimmed_path(audio_path: Path) -> Path:
    return audio_path.with_name(f"{audio_path.stem}-trimmed{audio_path.suffix}")
