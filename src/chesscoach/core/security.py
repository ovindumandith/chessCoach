"""Password hashing (stdlib scrypt) and JWT access tokens (PyJWT, HS256)."""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

import jwt

from chesscoach.core.config import Settings
from chesscoach.db.types import utcnow

# scrypt parameters: N=2^14, r=8, p=1 (~16 MB, OWASP-acceptable interactive setting).
_N, _R, _P = 2**14, 8, 1
_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, base64.b64decode(digest))


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def create_access_token(settings: Settings, user_id: uuid.UUID, role: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    lifetime = timedelta(minutes=settings.access_token_minutes)
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + lifetime,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=_ALGORITHM), int(
        lifetime.total_seconds()
    )


def decode_access_token(settings: Settings, token: str) -> uuid.UUID | None:
    """User id from a valid, unexpired token; None otherwise."""
    try:
        payload = jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None
