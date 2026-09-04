"""Password hashing with stdlib scrypt.

Stored format: scrypt$<n>$<r>$<p>$<salt_b64>$<key_b64> so parameters can be
raised later while old hashes keep verifying with their recorded cost.
"""

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_LEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN
    )
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(key).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    # Malformed stored values (empty, truncated, foreign format) must fail
    # closed without raising: this sits on the login path.
    try:
        scheme, n_s, r_s, p_s, salt_b64, key_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(key_b64.encode("ascii"))
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
        )
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(key, expected)
