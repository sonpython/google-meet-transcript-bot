"""Bearer auth ASGI wrapper for the MCP server.

The SDK's own auth stack demands OAuth metadata, so auth is enforced here
instead: every HTTP request must carry a valid personal API key or the
ADMIN_TOKEN. Non-HTTP scopes (lifespan) pass through untouched or the
session manager never starts.
"""

import hmac
import json
from pathlib import Path

from src.auth.api_key import hash_api_key
from src.mcp_server.queries import read_only_connect


class BearerAuthASGI:
    def __init__(self, app, db_path: Path, admin_token: str) -> None:
        self.app = app
        self.db_path = db_path
        self.admin_token = admin_token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = dict(scope.get("headers") or {}).get(b"authorization", b"").decode("latin-1")
        token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        if not token or not verify_key(token, self.db_path, self.admin_token):
            await _send_unauthorized(send)
            return
        await self.app(scope, receive, send)


def verify_key(key: str, db_path: Path, admin_token: str) -> bool:
    if not key:
        return False
    if admin_token and hmac.compare_digest(key.encode("utf-8"), admin_token.encode("utf-8")):
        return True
    key_hash = hash_api_key(key)
    try:
        conn = read_only_connect(db_path)
    except Exception:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM users WHERE api_key_hash = ? AND is_active = 1", (key_hash,)
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


async def _send_unauthorized(send) -> None:
    body = json.dumps({"error": "unauthorized"}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"www-authenticate", b"Bearer"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
