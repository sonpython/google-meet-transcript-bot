"""FastAPI auth dependencies.

Settings are always resolved through the health_server module attribute so
the existing test pattern (monkeypatching health_server.load_settings)
covers the whole app.
"""

from fastapi import HTTPException, Request

from src import health_server as core
from src.auth.request_auth import AuthContext, authenticate


def get_auth(request: Request, allow_cookie: bool = True) -> AuthContext | None:
    settings = core.load_settings()
    return authenticate(
        headers=request.headers,
        query=str(request.url.query or ""),
        admin_token=settings.admin_token or "",
        db_path=settings.db_path,
        allow_cookie=allow_cookie,
    )


def require_auth(request: Request) -> AuthContext:
    context = get_auth(request, allow_cookie=True)
    if context is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return context


def require_admin(request: Request) -> AuthContext:
    context = require_auth(request)
    if not context.is_admin:
        raise HTTPException(status_code=403, detail="forbidden")
    return context
