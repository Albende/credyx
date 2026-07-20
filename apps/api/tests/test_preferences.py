"""Tests for /api/auth/me/preferences (Wave 0.3)."""
from __future__ import annotations


async def test_get_preferences_returns_dict(client, make_user, auth_headers):
    user = await make_user("prefs.empty@example.com")
    r = await client.get("/api/auth/me/preferences", headers=auth_headers(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "preferences" in body
    assert isinstance(body["preferences"], dict)
    assert body["preferences"] == {}


async def test_patch_preferences_with_valid_theme_persists(client, make_user, auth_headers):
    user = await make_user("prefs.theme@example.com")
    h = auth_headers(user)

    p = await client.patch(
        "/api/auth/me/preferences", json={"theme": "light"}, headers=h
    )
    assert p.status_code == 200, p.text
    assert p.json()["preferences"]["theme"] == "light"

    g = await client.get("/api/auth/me/preferences", headers=h)
    assert g.status_code == 200, g.text
    assert g.json()["preferences"]["theme"] == "light"


async def test_patch_preferences_drops_unknown_keys(client, make_user, auth_headers):
    user = await make_user("prefs.unknown@example.com")
    h = auth_headers(user)

    p = await client.patch(
        "/api/auth/me/preferences",
        json={"theme": "dark", "evil_flag": True, "another_unknown": 42},
        headers=h,
    )
    assert p.status_code == 200, p.text
    body = p.json()["preferences"]
    assert body.get("theme") == "dark"
    assert "evil_flag" not in body
    assert "another_unknown" not in body


async def test_patch_preferences_with_invalid_theme_value(client, make_user, auth_headers):
    user = await make_user("prefs.bad@example.com")
    h = auth_headers(user)
    p = await client.patch(
        "/api/auth/me/preferences", json={"theme": "pink"}, headers=h
    )
    # Pydantic v2 schema validation surfaces as 422.
    assert p.status_code in {400, 422}, p.text
