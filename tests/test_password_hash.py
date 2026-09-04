from src.auth.password_hash import hash_password, verify_password


def test_hash_then_verify() -> None:
    stored = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", stored)


def test_wrong_password_fails() -> None:
    stored = hash_password("s3cret-pass")
    assert not verify_password("wrong-pass", stored)


def test_same_password_hashes_differ_but_both_verify() -> None:
    first = hash_password("repeat-me")
    second = hash_password("repeat-me")
    assert first != second
    assert verify_password("repeat-me", first)
    assert verify_password("repeat-me", second)


def test_stored_format_records_parameters() -> None:
    stored = hash_password("anything")
    scheme, n, r, p, salt, key = stored.split("$")
    assert scheme == "scrypt"
    assert int(n) == 16384 and int(r) == 8 and int(p) == 1
    assert salt and key


def test_malformed_stored_values_fail_closed() -> None:
    for garbage in ("", "garbage", "scrypt$16384$8$1$onlyfive", "md5$1$2$3$abc$def", "scrypt$x$8$1$!!$!!", None):
        if garbage is None:
            assert not verify_password("pw", "")
        else:
            assert not verify_password("pw", garbage)
