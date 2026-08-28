import pytest

from distributed_job_queue.auth.security import hash_password, token_hash, verify_password


def test_passwords_use_one_way_argon2_hashes():
    password = "correct-horse-battery-staple"

    password_hash = hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, password) is True
    assert verify_password(password_hash, "wrong-password") is False


def test_password_hashing_rejects_short_passwords():
    with pytest.raises(ValueError, match="at least 12"):
        hash_password("too-short")


def test_opaque_tokens_are_hashed_before_persistence():
    assert token_hash("secret-token") != "secret-token"
    assert len(token_hash("secret-token")) == 64
