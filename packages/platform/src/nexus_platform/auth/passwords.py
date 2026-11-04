"""Password hashing with the standard library scrypt KDF.

Hashes are stored as `scrypt$<n>$<r>$<p>$<salt>$<digest>` (base64 without padding). Verification
uses constant-time comparison and tolerates malformed stored values by returning False.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4))


def validate_new_password(password: str) -> None:
    """Reject passwords that are too short or too long; the message is safe to show users."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return hash_password_unchecked(password)


def hash_password_unchecked(password: str) -> str:
    """Hash a password without the length policy.

    Only the operator bootstrap that seeds the default space account may call this (see
    nexus_platform.bootstrap). Every user-facing path must use hash_password.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest))
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _unb64(digest))


# Hashed once at import so unknown usernames spend comparable time to real ones.
DUMMY_HASH = hash_password("dummy-password-for-timing")
