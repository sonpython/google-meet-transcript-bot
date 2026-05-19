import asyncio
import json
import os
import threading
import time
from pathlib import Path

from src.config import load_settings
from src.health_server import serve_forever
from src.main import main
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


def run() -> None:
    threading.Thread(target=serve_forever, daemon=True).start()
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
