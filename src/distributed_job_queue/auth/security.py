"""Password hashing and opaque credential helpers."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SESSION_COOKIE_NAME = "djq_session"
CSRF_COOKIE_NAME = "djq_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

_password_hasher = PasswordHasher()
_dummy_password_hash = _password_hasher.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return _password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    candidate_hash = password_hash or _dummy_password_hash
    try:
        verified = _password_hasher.verify(candidate_hash, password)
    except (InvalidHashError, VerificationError):
        return False
    return bool(verified and password_hash is not None)


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
