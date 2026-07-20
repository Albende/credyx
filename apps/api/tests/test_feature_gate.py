"""Tests for plan-based feature gating and quota enforcement."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.app.db import UsageWindow
from apps.api.app.feature_gate import consume_quota, requires_feature
from apps.api.app.main import app


_test_router = APIRouter(prefix="/_fg_test")


@_test_router.get("/risk")
async def _risk_route(_dep: None = Depends(requires_feature("risk_analysis"))):
    return {"ok": True}


@_test_router.get("/search")
async def _search_route(_dep: None = Depends(consume_quota("searches", UsageWindow.day))):
    return {"ok": True}


# Mount once; subsequent imports re-use the same paths.
if not any(getattr(r, "path", "") == "/_fg_test/risk" for r in app.routes):
    app.include_router(_test_router)


async def test_admin_bypasses_feature_and_quota(client, make_user, auth_headers):
    admin = await make_user("admin@example.com", role="admin")
    h = auth_headers(admin)

    r1 = await client.get("/_fg_test/risk", headers=h)
    assert r1.status_code == 200, r1.text

    # Admins skip the quota path entirely — 50 hits should still all pass.
    for _ in range(15):
        r = await client.get("/_fg_test/search", headers=h)
        assert r.status_code == 200, r.text


async def test_free_user_search_quota_enforced(client, make_user, auth_headers):
    user = await make_user("freebie@example.com")
    h = auth_headers(user)

    # FREE_PLAN_LIMITS['searches_per_day'] == 10
    for i in range(10):
        r = await client.get("/_fg_test/search", headers=h)
        assert r.status_code == 200, f"call {i + 1} returned {r.status_code}: {r.text}"
    r11 = await client.get("/_fg_test/search", headers=h)
    assert r11.status_code == 429, r11.text
    assert "quota_exceeded" in r11.text


async def test_free_user_blocked_from_risk_analysis_feature(client, make_user, auth_headers):
    user = await make_user("nofeat@example.com")
    r = await client.get("/_fg_test/risk", headers=auth_headers(user))
    assert r.status_code == 403
    assert "feature_unavailable" in r.text
