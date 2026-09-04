from src.auth.api_key import generate_api_key, hash_api_key


def test_generate_unique_with_prefix() -> None:
    first = generate_api_key()
    second = generate_api_key()
    assert first != second
    assert first.startswith("mak_") and second.startswith("mak_")


def test_hash_is_stable_hex_and_not_plaintext() -> None:
    key = generate_api_key()
    digest = hash_api_key(key)
    assert digest == hash_api_key(key)
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest != key
