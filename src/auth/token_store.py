import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class TokenStoreError(RuntimeError):
    pass


class TokenStore:
    def __init__(self, path: Path, passphrase: str | None) -> None:
        if not passphrase:
            raise TokenStoreError("TOKEN_PASSPHRASE is required")
        self.path = path
        key = hashlib.sha256(passphrase.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = self._fernet.encrypt(json.dumps(payload).encode("utf-8"))
        self.path.write_bytes(token)
        self.path.chmod(0o600)

    def load(self) -> dict[str, Any]:
        try:
            raw = self.path.read_bytes()
            decoded = self._fernet.decrypt(raw)
            payload = json.loads(decoded.decode("utf-8"))
        except FileNotFoundError as exc:
            raise TokenStoreError(f"Token file not found: {self.path}") from exc
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise TokenStoreError("Token file could not be decrypted or parsed") from exc
        if not isinstance(payload, dict):
            raise TokenStoreError("Token payload must be a JSON object")
        return payload
