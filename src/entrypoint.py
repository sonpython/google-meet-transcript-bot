import asyncio
import json
import os
import threading
import time
from pathlib import Path

from src.config import load_settings
from src.health_server import serve_forever
from src.main import main
from src.mcp_server.supervisor import start_mcp_server_if_enabled
from src.runtime_audio import start_virtual_audio_if_enabled
from src.runtime_status import STATUS


def _missing_runtime_inputs() -> list[str]:
    settings = load_settings()
    missing: list[str] = []
    if not settings.token_passphrase or settings.token_passphrase.startswith("replace-with-"):
        missing.append("TOKEN_PASSPHRASE")
    if not settings.storage_passphrase or settings.storage_passphrase.startswith("replace-with-"):
        missing.append("STORAGE_PASSPHRASE")
    client_secret_path = Path(settings.google_oauth_client_secrets)
    if not client_secret_path.exists():
        missing.append(f"GOOGLE_OAUTH_CLIENT_SECRETS:{settings.google_oauth_client_secrets}")
    elif not _looks_like_oauth_client_secret(client_secret_path):
        missing.append(f"GOOGLE_OAUTH_CLIENT_SECRETS_INVALID:{settings.google_oauth_client_secrets}")
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not Path(settings.token_store_path).exists():
        missing.append(f"TOKEN_STORE_PATH:{settings.token_store_path}")
    if not Path(settings.storage_state_path).exists():
        missing.append(f"STORAGE_STATE_PATH:{settings.storage_state_path}")
    if not Path(settings.bot_user_data_dir).exists():
        missing.append(f"BOT_USER_DATA_DIR:{settings.bot_user_data_dir}")
    return missing


def _looks_like_oauth_client_secret(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    client = payload.get("installed") or payload.get("web")
    return isinstance(client, dict) and bool(client.get("client_id")) and bool(client.get("client_secret"))


def _hold_degraded(missing: list[str]) -> None:
    STATUS.set("degraded", "missing runtime inputs", missing=missing)
    while True:
        time.sleep(300)


def _seed_admin_user() -> None:
    # First start after the multi-user upgrade: USER_EMAIL becomes the admin
    # row (no password until set via /admin/users). No-op when users exist.
    from src.auth.user_store import UserStore
    from src.state.db import connect

    settings = load_settings()
    try:
        conn = connect(settings.db_path)
        try:
            UserStore(conn).seed_admin(settings.user_email)
        finally:
            conn.close()
    except Exception:
        pass


def run() -> None:
    _seed_admin_user()
    threading.Thread(target=serve_forever, daemon=True).start()
    # Before the degraded hold: transcript access via MCP keeps working even
    # while calendar credentials are missing.
    start_mcp_server_if_enabled()
    start_virtual_audio_if_enabled()
    missing = _missing_runtime_inputs()
    if missing and os.getenv("ALLOW_DEGRADED_START", "true").lower() == "true":
        _hold_degraded(missing)
    STATUS.set("running", "bot loop starting")
    try:
        asyncio.run(main())
    except Exception as exc:
        STATUS.set("failed", str(exc))
        raise


if __name__ == "__main__":
    run()
