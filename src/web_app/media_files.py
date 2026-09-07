"""Resolve meeting media files to FileResponse (Range handled by Starlette)."""

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from src import health_server as core


def audio_response(meet_code: str, index: int, mode: str) -> FileResponse:
    detail = core._meeting_detail(meet_code, audio_mode=mode)
    segments = detail.get("files", {}).get("audio_segments", [])
    audio = segments[index] if 0 <= index < len(segments) else detail.get("files", {}).get("audio", {})
    path = Path(audio.get("path", ""))
    if not audio.get("exists") or not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path, media_type="audio/ogg; codecs=opus", headers={"Cache-Control": "no-store"}
    )


def screenshot_response(meet_code: str, index: int) -> FileResponse:
    detail = core._meeting_detail(meet_code)
    screenshots = detail.get("files", {}).get("screenshots", [])
    shot = screenshots[index] if 0 <= index < len(screenshots) else {}
    path = Path(shot.get("path", ""))
    if not shot.get("exists") or not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


def audio_mode(value: str | None) -> str:
    return "full" if (value or "").strip().lower() == "full" else "default"
