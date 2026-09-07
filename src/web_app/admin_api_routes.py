"""/admin/api/* routes, admin-gated. Logic stays in src.health_server and
src.web.admin_users; handlers here only translate HTTP."""

from fastapi import APIRouter, Depends, HTTPException, Request

from src import health_server as core
from src.runtime_status import STATUS
from src.web import admin_users
from src.web_app.dependencies import require_admin
from src.web_app.media_files import audio_mode, audio_response, screenshot_response

router = APIRouter(prefix="/admin/api", dependencies=[Depends(require_admin)])


async def _json_body(request: Request) -> dict:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


@router.get("/status")
def status() -> dict:
    return STATUS.snapshot()


@router.get("/meetings")
def meetings() -> dict:
    return {"meetings": core._list_meetings()}


@router.get("/settings")
def settings() -> dict:
    return {"settings": core._admin_settings()}


@router.get("/upcoming")
def upcoming() -> dict:
    return {"events": core._upcoming_events()}


@router.get("/users")
def users() -> dict:
    return admin_users.list_users(core.load_settings().db_path)


@router.get("/meetings/{code}/audio-meta")
def meeting_audio_meta(code: str, mode: str = "default") -> dict:
    detail = core._meeting_detail(code, include_audio_peaks=True, audio_mode=audio_mode(mode))
    return {"audio_segments": detail.get("files", {}).get("audio_segments", [])}


@router.get("/meetings/{code}/audio")
def meeting_audio(code: str, index: int = 0, mode: str = "default"):
    return audio_response(code, index, audio_mode(mode))


@router.get("/meetings/{code}/screenshots")
def meeting_screenshot(code: str, index: int = 0):
    return screenshot_response(code, index)


@router.get("/meetings/{code}")
def meeting_detail(code: str) -> dict:
    return {"meeting": core._meeting_detail(code)}


@router.post("/users")
async def create_user(request: Request) -> dict:
    return admin_users.create_user(core.load_settings().db_path, await _json_body(request))


@router.post("/users/{user_id}/password")
async def set_user_password(user_id: int, request: Request) -> dict:
    return admin_users.set_password(core.load_settings().db_path, user_id, await _json_body(request))


@router.post("/users/{user_id}/rotate-key")
def rotate_user_key(user_id: int) -> dict:
    return admin_users.rotate_key(core.load_settings().db_path, user_id)


@router.post("/users/{user_id}/revoke-key")
def revoke_user_key(user_id: int) -> dict:
    return admin_users.revoke_key(core.load_settings().db_path, user_id)


@router.post("/users/{user_id}/active")
async def set_user_active(user_id: int, request: Request) -> dict:
    return admin_users.set_active(core.load_settings().db_path, user_id, await _json_body(request))


@router.post("/manual-join")
async def manual_join(request: Request) -> dict:
    return core._request_manual_join(await _json_body(request))


@router.post("/settings/audio-retention")
async def audio_retention(request: Request) -> dict:
    return core._update_audio_retention(await _json_body(request))


@router.post("/meetings/{code}/rejoin")
def rejoin(code: str) -> dict:
    return core._request_rejoin(code)


@router.post("/meetings/{code}/force-out")
def force_out(code: str) -> dict:
    return core._request_force_out(code)


@router.post("/meetings/{code}/delete")
def delete_meeting(code: str) -> dict:
    return core._delete_meeting(code)


@router.post("/meetings/{code}/regenerate")
async def regenerate(code: str, request: Request) -> dict:
    return core._request_regenerate(code, await _json_body(request))


@router.post("/meetings/{code}/regenerate-transcript")
def regenerate_transcript(code: str) -> dict:
    return core._request_regenerate_transcript(code)


@router.get("/{rest:path}")
def unknown_get(rest: str):
    raise HTTPException(status_code=404, detail="not found")


@router.post("/{rest:path}")
def unknown_post(rest: str):
    raise HTTPException(status_code=404, detail="not found")
