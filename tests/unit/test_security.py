from datetime import timedelta

import jwt
import pytest

from chesscoach.core.config import Settings
from chesscoach.core.ratelimit import RateLimitedError, SlidingWindowLimiter
from chesscoach.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from chesscoach.db.types import utcnow

S = Settings(app_secret_key="x" * 40)


def test_password_hash_roundtrip_and_unique_salts():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("correct horse battery", h1)
    assert not verify_password("wrong", h1)


@pytest.mark.parametrize("stored", [None, "", "md5$abc", "scrypt$1$2", "scrypt$x$y$z$a$b"])
def test_malformed_hashes_never_verify(stored):
    assert not verify_password("anything", stored)


def test_token_roundtrip():
    import uuid

    uid = uuid.uuid4()
    token, expires_in = create_access_token(S, uid, "coach")
    assert decode_access_token(S, token) == uid
    assert expires_in == 3600


def test_rejects_expired_tampered_wrong_key_and_alg_none():
    import uuid

    uid = str(uuid.uuid4())
    now = utcnow()
    expired = jwt.encode(
        {"sub": uid, "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        S.app_secret_key,
        algorithm="HS256",
    )
    assert decode_access_token(S, expired) is None
    other_key = jwt.encode(
        {"sub": uid, "iat": now, "exp": now + timedelta(hours=1)}, "y" * 40, algorithm="HS256"
    )
    assert decode_access_token(S, other_key) is None
    unsigned = jwt.encode(
        {"sub": uid, "iat": now, "exp": now + timedelta(hours=1)}, None, algorithm="none"
    )
    assert decode_access_token(S, unsigned) is None
    good, _ = create_access_token(S, uuid.UUID(uid), "coach")
    head, body, sig = good.split(".")
    assert decode_access_token(S, f"{head}.{body}.{sig[::-1]}") is None
    assert decode_access_token(S, "not-a-token") is None


def test_production_refuses_placeholder_secret():
    with pytest.raises(RuntimeError):
        Settings(app_env="production", app_secret_key="replace_me").check_security()
    with pytest.raises(RuntimeError):
        Settings(app_env="production", app_secret_key="short").check_security()
    Settings(app_env="production", app_secret_key="z" * 40).check_security()


@pytest.mark.parametrize(
    "env, bypass, allowed",
    [
        ("test", False, True),
        ("development", False, False),
        ("development", True, True),
        ("production", True, False),
    ],
)
def test_dev_auth_only_where_allowed(env, bypass, allowed):
    assert Settings(app_env=env, auth_dev_bypass=bypass).dev_auth_allowed is allowed


def test_sliding_window_limiter():
    limiter = SlidingWindowLimiter()
    for _ in range(3):
        limiter.hit("k", limit=3, window_seconds=60)
    with pytest.raises(RateLimitedError) as exc:
        limiter.hit("k", limit=3, window_seconds=60)
    assert exc.value.details["retry_after_seconds"] >= 1
    limiter.hit("other", limit=3, window_seconds=60)  # keys are independent
