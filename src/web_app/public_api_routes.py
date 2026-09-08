"""/api/* routes: same URLs, auth, and response shapes as the legacy
stdlib server. All meeting logic stays in src.health_server."""

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request

from src import health_server as core
from src.auth.api_key_store import ApiKeyStore
from src.auth.request_auth import AuthContext
from src.state.db import connect
from src.web_app.dependencies import require_auth
from src.web_app.media_files import audio_mode, audio_response, screenshot_response

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _require_session(request: Request) -> AuthContext:
    # Key management needs a logged-in browser session: a stolen API key must
    # not be able to mint replacement keys for itself.
    context = require_auth(request)
    if context.kind != "session" or context.user_id is None:
        raise HTTPException(status_code=403, detail="key management requires a web login session")
    return context


@router.post("/manual-join")
async def manual_join(request: Request) -> dict:
    # Any authenticated user may ask the bot to join: same trust model as
    # inviting the bot on the calendar (D6).
    try:
        payload = await request.json()
        payload = payload if isinstance(payload, dict) else {}
    except Exception:
        payload = {}
    return core._request_manual_join(payload)


@router.get("/keys")
def list_keys(request: Request) -> dict:
    context = _require_session(request)
    conn = connect(core.load_settings().db_path)
    try:
        store = ApiKeyStore(conn)
        return {"keys": [store.public_row(row) for row in store.list_for_user(context.user_id)]}
    finally:
        conn.close()


@router.post("/keys")
async def create_key(request: Request) -> dict:
    context = _require_session(request)
    try:
        payload = await request.json()
        payload = payload if isinstance(payload, dict) else {}
    except Exception:
        payload = {}
    expires_days = payload.get("expires_days")
    conn = connect(core.load_settings().db_path)
    try:
        store = ApiKeyStore(conn)
        plaintext, row = store.create(
            context.user_id,
            str(payload.get("name", "") or ""),
            int(expires_days) if expires_days else None,
        )
        return {"ok": True, "api_key": plaintext, "key": store.public_row(row)}
    finally:
        conn.close()


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, request: Request) -> dict:
    context = _require_session(request)
    conn = connect(core.load_settings().db_path)
    try:
        if not ApiKeyStore(conn).delete(key_id, context.user_id):
            raise HTTPException(status_code=404, detail="key not found")
        return {"ok": True}
    finally:
        conn.close()


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
