import pytest

from app.auth.service import (
    hash_password,
    hash_token,
    normalize_username,
    validate_credentials,
    verify_password,
)
from app.domain.errors import DomainError


def test_username_is_normalized():
    assert normalize_username("  Demo ") == "demo"
    assert validate_credentials(" Juan.Perez ", "secret1") == "juan.perez"


@pytest.mark.parametrize(
    ("username", "password", "field"),
    [
        ("ab", "secret1", "username"),  # too short
        ("a" * 31, "secret1", "username"),  # too long
        ("juan perez", "secret1", "username"),  # spaces
        ("juan@mail", "secret1", "username"),
        ("juan", "12345", "password"),  # < 6
        ("juan", "x" * 73, "password"),  # bcrypt limit
    ],
)
def test_invalid_credentials_are_rejected(username, password, field):
    with pytest.raises(DomainError) as info:
        validate_credentials(username, password)
    assert info.value.code == "INVALID_INPUT"
    assert info.value.details["field"] == field


def test_password_hash_roundtrip():
    hashed = hash_password("secret123")
    assert hashed != "secret123" and hashed.startswith("$2")
    assert verify_password("secret123", hashed)
    assert not verify_password("secret124", hashed)
    assert not verify_password("secret123", "not-a-bcrypt-hash")


def test_token_hash_is_sha256_hex():
    digest = hash_token("abc")
    assert len(digest) == 64 and digest != "abc"
    assert hash_token("abc") == digest
