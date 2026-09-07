"""/api/* routes: same URLs, auth, and response shapes as the legacy
stdlib server. All meeting logic stays in src.health_server."""

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request

from src import health_server as core
from src.web_app.dependencies import require_auth
from src.web_app.media_files import audio_mode, audio_response, screenshot_response

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _params(request: Request) -> dict[str, list[str]]:
    return parse_qs(str(request.url.query or ""))


@router.get("/meetings")
def list_meetings(request: Request) -> dict:
    return core._api_list_meetings(_params(request))


@router.get("/transcripts")
def transcripts(request: Request) -> dict:
    return core._api_transcripts(_params(request))


@router.get("/meetings/{code}/audio")
def meeting_audio(code: str, index: int = 0, mode: str = "default"):
    meet_code = _code(code)
    return audio_response(meet_code, index, audio_mode(mode))


@router.get("/meetings/{code}/screenshots")
def meeting_screenshot(code: str, index: int = 0):
    return screenshot_response(_code(code), index)


@router.get("/meetings/{code}")
def meeting_detail(code: str) -> dict:
    return {"meeting": core._api_meeting_detail(_code(code))}


@router.get("/{rest:path}")
def unknown(rest: str):
    raise HTTPException(status_code=404, detail="not found")


@router.post("/{rest:path}")
def method_not_allowed(rest: str):
    raise HTTPException(status_code=405, detail="method not allowed")


def _code(raw: str) -> str:
    meet_code = core._normalize_meet_code(raw)
    if not meet_code:
        raise HTTPException(status_code=400, detail="invalid Meet code")
    return meet_code
