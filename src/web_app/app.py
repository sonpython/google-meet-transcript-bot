"""FastAPI application factory: one process serves the admin UI, user web,
public API, and the MCP server (mounted at /mcp behind Bearer auth)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from src import health_server as core
from src.mcp_server.bearer_auth import BearerAuthASGI
from src.mcp_server.server import build_server
from src.web_app.admin_api_routes import router as admin_api_router
from src.web_app.pages_routes import router as pages_router
from src.web_app.public_api_routes import router as public_api_router


def create_app() -> FastAPI:
    settings = core.load_settings()
    mcp_http = build_server(settings.db_path).streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=False,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # The mounted MCP app's session manager only starts inside its own
        # lifespan, which Starlette does not run for sub-apps.
        async with mcp_http.router.lifespan_context(mcp_http):
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(pages_router)
    app.include_router(public_api_router)
    app.include_router(admin_api_router)
    app.mount("/mcp", BearerAuthASGI(mcp_http, settings.db_path, settings.admin_token or ""))

    # Keep the legacy error body shape ({"error": ...}) that the page JS and
    # API clients already parse.
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        return JSONResponse({"error": str(exc)}, status_code=500)

    return app
