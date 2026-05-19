from pathlib import Path
from typing import Any

from src.auth.token_store import TokenStore


class StorageStateStore:
    def __init__(self, path: Path, passphrase: str | None) -> None:
        self._store = TokenStore(path, passphrase)

    def exists(self) -> bool:
        return self._store.exists()

    def save(self, state: dict[str, Any]) -> None:
        self._store.save(state)

    def load(self) -> dict[str, Any] | None:
        if not self.exists():
            return None
        return self._store.load()
