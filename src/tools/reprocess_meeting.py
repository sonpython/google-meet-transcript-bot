import argparse
import asyncio
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from src.config import load_settings
from src.gemini.client import GeminiClient
from src.gemini.pipeline import GeminiPipeline, _slug
from src.models.meeting_result import MeetingResult
from src.state.db import connect
from src.state.meetings_repo import MeetingsRepo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate transcript, summary, minutes, and notes for a meeting.")
    parser.add_argument("--meet-code", required=True)
    parser.add_argument("--clear-meta", action="store_true", help="Remove cached .opus.meta.json files for this meeting.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    meet_code = _safe_meet_code(args.meet_code)
    settings = load_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required")

    repo = MeetingsRepo(connect(settings.db_path))
    row = repo.get(meet_code)
    if not row:
        raise RuntimeError(f"Meeting not found: {meet_code}")

    audio_paths = sorted(
        (path for path in settings.audio_dir.glob(f"{meet_code}*.opus") if path.stat().st_size > 0),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not audio_paths:
        raise RuntimeError(f"No audio files found for {meet_code}")

    if args.clear_meta:
        for path in settings.audio_dir.glob(f"{meet_code}*.opus.meta.json"):
            path.unlink(missing_ok=True)

    title = row["title"] or meet_code
    participants = _participants(row)
    pipeline = GeminiPipeline(GeminiClient(settings.gemini_api_key, settings.gemini_model), settings.output_dir)
    output_paths = _output_paths(settings.output_dir, title or meet_code)
    for path in output_paths:
        path.unlink(missing_ok=True)

    results = []
    for index, audio_path in enumerate(audio_paths, start=1):
        print(f"reprocess {meet_code}: segment {index}/{len(audio_paths)} {audio_path}")
        results.append(
            MeetingResult(
                meet_code=meet_code,
                audio_path=audio_path,
                duration_sec=_duration_seconds(audio_path),
                exit_reason="reprocess",
                participant_names=participants,
                title=title,
                admin_instruction=str(row["admin_instruction"] or "") if "admin_instruction" in row.keys() else "",
            )
        )

    if not results:
        raise RuntimeError(f"No output generated for {meet_code}")
    transcript_path, summary_path, minutes_path, notes_path = await pipeline.process_many(tuple(results), append=False)
    repo.mark_delivered(
        meet_code,
        str(notes_path),
        transcript_path=str(transcript_path),
        summary_path=str(summary_path),
        minutes_path=str(minutes_path),
    )
    print(json.dumps({"meet_code": meet_code, "segments": [str(path) for path in audio_paths]}, ensure_ascii=False))


def _safe_meet_code(value: str) -> str:
    cleaned = value.strip().lower()
    if not re.fullmatch(r"[a-z]{3}-[a-z]{4}-[a-z]{3}", cleaned):
        raise ValueError(f"Invalid meet code: {value}")
    return cleaned


def _participants(row) -> tuple[str, ...]:
    attendees = []
    if row["organizer"]:
        attendees.append(row["organizer"])
    if row["attendees"]:
        try:
            attendees.extend(json.loads(row["attendees"]))
        except json.JSONDecodeError:
            pass
    return tuple(dict.fromkeys(str(item) for item in attendees if item))


def _output_paths(output_dir: Path, title: str) -> tuple[Path, Path, Path, Path]:
    slug = _slug(title)
    return (
        output_dir / f"transcript-{slug}.md",
        output_dir / f"summary-{slug}.md",
        output_dir / f"meeting-minutes-{slug}.md",
        output_dir / f"meeting-notes-{slug}.md",
    )


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


if __name__ == "__main__":
    asyncio.run(main())
