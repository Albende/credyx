"""Tests for /api/admin/* — every endpoint guarded by require_admin."""
from __future__ import annotations


async def test_list_users_as_admin_returns_paginated(client, make_user, auth_headers):
    admin = await make_user("root@example.com", role="admin")
    # Seed two non-admin users.
    await make_user("u1@example.com")
    await make_user("u2@example.com")

    r = await client.get("/api/admin/users", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "users" in body
    assert "page" in body
    assert "page_size" in body
    assert "total" in body
    assert isinstance(body["users"], list)
    assert body["total"] >= 3
    assert body["page"] == 1


async def test_list_users_as_regular_user_forbidden(client, make_user, auth_headers):
    user = await make_user("peon@example.com")
    r = await client.get("/api/admin/users", headers=auth_headers(user))
    assert r.status_code == 403
    assert "admin_required" in r.text


async def test_admin_endpoints_reject_anonymous(client):
    r = await client.get("/api/admin/users")
    assert r.status_code == 401
