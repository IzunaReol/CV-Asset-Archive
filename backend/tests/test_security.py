from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_roundtrip():
    encoded = hash_password("admin")
    assert encoded != "admin"
    assert verify_password("admin", encoded)
    assert not verify_password("wrong", encoded)


def test_access_token_roundtrip():
    token, expiry = create_access_token("user-id", "admin", ["admin"])
    claims = decode_access_token(token)
    assert claims["sub"] == "user-id"
    assert claims["roles"] == ["admin"]
    assert expiry.tzinfo is not None
