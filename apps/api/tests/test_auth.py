"""Tests for /api/auth/* — register, login, refresh, password reset, me."""
from __future__ import annotations

from apps.api.app.config import get_settings


async def test_register_with_bootstrap_email_grants_admin(client, monkeypatch):
    """Registering with the bootstrap-admin email yields role=admin
    and dev-mode auto-verifies the email.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "bootstrap_admin_email", "boss@example.com")
    # Dev defaults: smtp_host=localhost + smtp_port=1025 → auto-verify is on.
    r = await client.post(
        "/api/auth/register",
        json={
            "email": "Boss@example.com",
            "first_name": "Boss",
            "last_name": "Person",
            "password": "Sup3rSecret",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "admin"
    assert body["email_verified"] is True


async def test_register_twice_same_email_409(client):
    payload = {
        "email": "dup@example.com",
        "first_name": "Dup",
        "last_name": "User",
        "password": "Sup3rSecret",
    }
    r1 = await client.post("/api/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/auth/register", json=payload)
    assert r2.status_code == 409
    assert "email_already_registered" in r2.text


async def test_login_success_returns_access_and_refresh(client, make_user):
    await make_user("login.ok@example.com", password="Sup3rSecret")
    r = await client.post(
        "/api/auth/login",
        json={"email": "login.ok@example.com", "password": "Sup3rSecret"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_wrong_password_401(client, make_user):
    await make_user("login.wrong@example.com", password="Sup3rSecret")
    r = await client.post(
        "/api/auth/login",
        json={"email": "login.wrong@example.com", "password": "NotR1ght"},
    )
    assert r.status_code == 401
    assert "invalid_credentials" in r.text


async def test_me_with_valid_token(client, make_user, auth_headers):
    user = await make_user("me.ok@example.com")
    r = await client.get("/api/auth/me", headers=auth_headers(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "me.ok@example.com"
    assert body["role"] == "user"
    assert isinstance(body["plan_features"], dict)
    assert isinstance(body["plan_limits"], dict)


async def test_me_without_token_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_refresh_token_rotates_jti(client, make_user):
    user = await make_user("rotate@example.com", password="Sup3rSecret")
    login = await client.post(
        "/api/auth/login",
        json={"email": "rotate@example.com", "password": "Sup3rSecret"},
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    r1 = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r1.status_code == 200, r1.text

    # Reusing the original refresh token must now be revoked.
    r2 = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 401, r2.text
    assert "token_revoked" in r2.text


async def test_forgot_password_always_204(client, make_user):
    # Unknown email — still 204.
    r1 = await client.post(
        "/api/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert r1.status_code == 204

    # Known email — still 204.
    await make_user("known@example.com")
    r2 = await client.post(
        "/api/auth/forgot-password", json={"email": "known@example.com"}
    )
    assert r2.status_code == 204


async def test_reset_password_with_bad_token_400(client):
    r = await client.post(
        "/api/auth/reset-password",
        json={"token": "this-token-does-not-exist", "new_password": "Sup3rSecret"},
    )
    assert r.status_code == 400
    assert "invalid_or_expired_token" in r.text
