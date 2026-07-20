"""Tests for /api/billing/* — read-only endpoints (plans + my-subscription)."""
from __future__ import annotations


async def test_list_plans_returns_seeded_plans(client, session):
    """Without any plans in the DB the endpoint should still 200 with []."""
    r = await client.get("/api/billing/plans")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    # No plans seeded → empty list.
    assert body == []


async def test_list_plans_after_seeding(client, session):
    from apps.api.app.db import Plan

    p = Plan(
        slug="pro",
        name="Pro",
        description="Pro plan",
        price_monthly_cents=2900,
        price_yearly_cents=29000,
        currency="usd",
        features={"risk_analysis": True},
        limits={"searches_per_day": 10000},
    )
    session.add(p)
    await session.commit()

    r = await client.get("/api/billing/plans")
    assert r.status_code == 200, r.text
    body = r.json()
    slugs = [it["slug"] for it in body]
    assert "pro" in slugs


async def test_my_subscription_returns_null_when_no_active_sub(client, make_user, auth_headers):
    user = await make_user("subless@example.com")
    r = await client.get("/api/billing/me/subscription", headers=auth_headers(user))
    assert r.status_code == 200, r.text
    assert r.json() is None


async def test_my_subscription_requires_auth(client):
    r = await client.get("/api/billing/me/subscription")
    assert r.status_code == 401
