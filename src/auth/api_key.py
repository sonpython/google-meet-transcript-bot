"""Personal API key generation and hashing.

Keys are shown to the user exactly once; only the sha256 hex digest of the
full plaintext (prefix included) is ever stored.
"""

import hashlib
import secrets

API_KEY_PREFIX = "mak_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
