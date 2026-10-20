"""Real authentication with the development stub disabled."""

import pytest

from chesscoach import accounts
from chesscoach.core.config import get_settings
from chesscoach.db.enums import UserRole

API = "/api/v1"
PASSWORD = "a-long-test-password"


@pytest.fixture
def secured(client, monkeypatch):
    """Switch the running app to development mode with the header stub OFF."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_BYPASS", "false")
    monkeypatch.setenv("APP_SECRET_KEY", "k" * 40)
    get_settings.cache_clear()
    yield client
    get_settings.cache_clear()


def login(client, email, password=PASSWORD):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def bearer(client, email, password=PASSWORD):
    token = login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(db):
    return accounts.create_user(
        db, None, email="Admin@Example.org", password=PASSWORD, role=UserRole.ADMIN
    )


def test_requests_without_token_are_rejected(secured):
    resp = secured.get(f"{API}/students")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    # The dev header is ignored once the stub is disabled.
    assert (
        secured.get(
            f"{API}/students", headers={"X-Dev-User-Email": "dev-coach@chesscoach.local"}
        ).status_code
        == 401
    )


def test_login_and_me(secured, admin):
    body = login(secured, "  admin@example.ORG ").json()  # email is normalized
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    me = secured.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    ).json()
    assert me["email"] == "admin@example.org" and me["role"] == "admin"


def test_bad_credentials_look_identical(secured, admin):
    wrong = login(secured, "admin@example.org", "wrong-password-123")
    unknown = login(secured, "nobody@example.org")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_rate_limit(secured, admin):
    for _ in range(10):
        login(secured, "admin@example.org", "wrong-password-123")
    resp = login(secured, "admin@example.org")  # even the right password is now blocked
    assert resp.status_code == 429
    assert resp.json()["error"]["details"]["retry_after_seconds"] > 0


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "Bearer not.a.jwt"])
def test_malformed_or_invalid_tokens(secured, header):
    assert secured.get(f"{API}/auth/me", headers={"Authorization": header}).status_code == 401


def test_full_role_flow(secured, admin, db):
    admin_h = bearer(secured, "admin@example.org")
    assert (
        secured.post(
            f"{API}/users",
            headers=admin_h,
            json={"email": "coach@example.org", "password": PASSWORD, "role": "coach"},
        ).status_code
        == 201
    )
    coach_h = bearer(secured, "coach@example.org")
    # Coaches cannot create staff accounts.
    assert (
        secured.post(
            f"{API}/users",
            headers=coach_h,
            json={"email": "x@example.org", "password": PASSWORD, "role": "coach"},
        ).status_code
        == 403
    )

    mine = secured.post(
        f"{API}/students", headers=coach_h, json={"display_name": "Mine", "aliases": ["Me"]}
    ).json()
    other = secured.post(f"{API}/students", headers=admin_h, json={"display_name": "Other"}).json()
    weak = secured.post(
        f"{API}/students/{mine['id']}/account",
        headers=coach_h,
        json={"email": "kid@example.org", "password": "short"},
    )
    assert weak.status_code == 422
    created = secured.post(
        f"{API}/students/{mine['id']}/account",
        headers=coach_h,
        json={"email": "kid@example.org", "password": PASSWORD},
    )
    assert created.status_code == 201 and created.json()["role"] == "student"
    assert (
        secured.post(
            f"{API}/students/{mine['id']}/account",
            headers=coach_h,
            json={"email": "kid2@example.org", "password": PASSWORD},
        ).status_code
        == 409
    )
    # A coach cannot create an account for a student they do not coach.
    assert (
        secured.post(
            f"{API}/students/{other['id']}/account",
            headers=coach_h,
            json={"email": "kid3@example.org", "password": PASSWORD},
        ).status_code
        == 403
    )

    kid_h = bearer(secured, "kid@example.org")
    me = secured.get(f"{API}/auth/me", headers=kid_h).json()
    assert me["students"] == [{"student_id": mine["id"], "access_level": "self"}]
    assert secured.get(f"{API}/students/{mine['id']}", headers=kid_h).status_code == 200
    assert secured.get(f"{API}/students/{other['id']}", headers=kid_h).status_code == 403
    assert secured.get(f"{API}/students", headers=kid_h).json()["total"] == 1
    assert (
        secured.post(f"{API}/students", headers=kid_h, json={"display_name": "Nope"}).status_code
        == 403
    )


def test_change_password_and_inactive_user(secured, admin, db):
    h = bearer(secured, "admin@example.org")
    assert (
        secured.post(
            f"{API}/auth/change-password",
            headers=h,
            json={"current_password": "wrong-password-1", "new_password": "another-long-pass"},
        ).status_code
        == 401
    )
    assert (
        secured.post(
            f"{API}/auth/change-password",
            headers=h,
            json={"current_password": PASSWORD, "new_password": "another-long-pass"},
        ).status_code
        == 204
    )
    assert login(secured, "admin@example.org").status_code == 401
    assert login(secured, "admin@example.org", "another-long-pass").status_code == 200

    admin.is_active = False
    db.commit()
    assert secured.get(f"{API}/auth/me", headers=h).status_code == 403
    assert login(secured, "admin@example.org", "another-long-pass").status_code == 401


def test_expensive_routes_are_rate_limited(client, monkeypatch, mixed_pgn):
    monkeypatch.setenv("RATE_LIMIT_IMPORTS_PER_HOUR", "2")
    get_settings.cache_clear()
    sid = client.post(f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}).json()[
        "id"
    ]
    url = f"{API}/students/{sid}/games/import"
    files = {"file": ("g.pgn", mixed_pgn, "application/x-chess-pgn")}
    me = client.as_student(sid)
    assert [client.post(url, files=files, headers=me).status_code for _ in range(3)] == [
        201,
        201,
        429,
    ]
    get_settings.cache_clear()


def test_cors_allows_only_configured_origins(client):
    ok = client.options(
        f"{API}/students",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        f"{API}/students",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers
