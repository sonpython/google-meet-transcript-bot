"""HTML pages and auth flows: health/status, user web (/login, /app,
/account/password), admin pages and admin cookie login."""

from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from src import health_server as core
from src.runtime_status import STATUS
from src.web import admin_users
from src.web.user_routes import handle as user_handle
from src.web_app.dependencies import get_auth

router = APIRouter()


@router.get("/")
@router.get("/status")
@router.get("/healthz")
def health() -> dict:
    return STATUS.snapshot()


def _from_web_response(resp) -> Response:
    response = Response(content=resp.body, status_code=resp.status, media_type=resp.content_type)
    for key, value in resp.headers:
        response.headers[key] = value
    return response


async def _user_route(request: Request, method: str, path: str) -> Response:
    body = await request.body() if method == "POST" else b""
    context = get_auth(request)
    result = user_handle(method, path, request.headers, body, context, core.load_settings().db_path)
    return _from_web_response(result)


@router.get("/login")
async def login_page(request: Request):
    return await _user_route(request, "GET", "/login")


@router.post("/login")
async def login_submit(request: Request):
    return await _user_route(request, "POST", "/login")


@router.post("/logout-user")
async def logout_user(request: Request):
    return await _user_route(request, "POST", "/logout-user")


@router.get("/app")
async def app_page(request: Request):
    return await _user_route(request, "GET", "/app")


@router.post("/account/password")
async def account_password(request: Request):
    return await _user_route(request, "POST", "/account/password")


def _admin_page(request: Request, page_html: str) -> Response:
    context = get_auth(request)
    if context is None:
        return HTMLResponse(core._login_html())
    if not context.is_admin:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return HTMLResponse(page_html)


@router.get("/admin")
def admin_dashboard(request: Request):
    return _admin_page(request, core._admin_html())


@router.get("/admin/settings")
def admin_settings_page(request: Request):
    return _admin_page(request, core._settings_html())


@router.get("/admin/users")
def admin_users_page(request: Request):
    return _admin_page(request, admin_users.page_html())


@router.post("/admin/login")
async def admin_login(request: Request):
    body = (await request.body()).decode("utf-8")
    token = parse_qs(body).get("token", [""])[0]
    expected = core.load_settings().admin_token or ""
    if token and expected and token == expected:
        response = Response(status_code=303, headers={"Location": "/admin"})
        response.headers["Set-Cookie"] = f"admin_token={token}; Path=/admin; HttpOnly; SameSite=Lax"
        return response
    return HTMLResponse(core._login_html("Invalid token"), status_code=401)


@router.post("/admin/logout")
def admin_logout():
    response = Response(status_code=303, headers={"Location": "/admin"})
    response.headers["Set-Cookie"] = "admin_token=; Path=/admin; HttpOnly; SameSite=Lax; Max-Age=0"
    return response
