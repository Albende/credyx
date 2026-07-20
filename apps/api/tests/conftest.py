"""Backend test fixtures for the FastAPI app.

Spins up an in-memory SQLite database, a fakeredis instance, and an httpx
AsyncClient bound to the ASGI app. The Postgres-only ``JSONB`` columns are
rewritten to plain ``JSON`` for the SQLite dialect via a one-shot compiles
hook installed before any model metadata is touched.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


# JSONB must be teachable to SQLite BEFORE the ORM metadata is imported,
# otherwise Base.metadata.create_all() fails at compile time.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: D401
    return "JSON"


# SQLite (via aiosqlite) strips tzinfo on read. The production code stores
# tz-aware UTC datetimes everywhere, so when comparing cached `last_fetched_at`
# against `datetime.now(timezone.utc)` we hit "can't compare naive and aware".
# Re-attach UTC tz on every read by overriding DateTime result processing for
# the sqlite dialect.
from sqlalchemy.dialects.sqlite import base as _sqlite_base


def _coerce_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, _dt.datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=_dt.timezone.utc)
    return dt


_orig_result_proc = _sqlite_base.DATETIME.result_processor


def _patched_result_processor(self, dialect, coltype):
    base = _orig_result_proc(self, dialect, coltype)

    def _wrap(value):
        out = base(value) if base else value
        return _coerce_utc(out)

    return _wrap


_sqlite_base.DATETIME.result_processor = _patched_result_processor


import httpx
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import fakeredis.aioredis

from apps.api.app import auth as auth_mod
from apps.api.app import auth_routes as auth_routes_mod
from apps.api.app import rate_limit as rate_limit_mod
from apps.api.app.auth import create_access_token
from apps.api.app.db import (
    Base,
    BillingPeriod,
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
    get_session,
)
from apps.api.app.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so the engine and its connections survive
    across tests in the same module without aiosqlite tearing the loop down.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """Per-test session. We commit-as-you-go inside the app, so the easiest
    way to keep tests isolated is to drop-and-recreate all tables between
    tests rather than wrap in a savepoint.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with sm() as s:
        yield s


@pytest_asyncio.fixture
async def fake_redis(monkeypatch) -> fakeredis.aioredis.FakeRedis:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _fake_get_redis():
        return r

    monkeypatch.setattr(auth_mod, "_get_redis", _fake_get_redis)
    monkeypatch.setattr(auth_routes_mod, "_get_redis", _fake_get_redis)

    # Replace the IP rate limiter with a fakeredis-backed instance and bump
    # the per-minute limit so tests that fire many requests don't trip 429.
    fake_limiter = rate_limit_mod.RateLimiter(r, per_minute=100_000)
    monkeypatch.setattr(rate_limit_mod, "_limiter", fake_limiter)

    yield r
    await r.flushall()
    await r.aclose()


@pytest_asyncio.fixture
async def client(session, fake_redis) -> AsyncIterator[httpx.AsyncClient]:
    async def _get_session_override():
        # Yield a fresh session bound to the same engine so the route layer
        # can commit independently of the test's bookkeeping session.
        sm = async_sessionmaker(session.bind, expire_on_commit=False, class_=AsyncSession)
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = _get_session_override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def make_user(session):
    """Factory: create (and commit) a User, optionally subscribed to a plan."""

    async def _make(
        email: str,
        *,
        password: str = "Sup3rSecret",
        role: str = "user",
        plan_slug: str | None = None,
        email_verified: bool = True,
        first_name: str = "Test",
        last_name: str = "User",
    ) -> User:
        user = User(
            email=email.lower(),
            password_hash=auth_mod.hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=UserRole(role),
            email_verified_at=__import__("datetime").datetime.utcnow() if email_verified else None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        if plan_slug:
            plan = Plan(
                slug=plan_slug,
                name=plan_slug.title(),
                description=f"{plan_slug} plan",
                price_monthly_cents=1000,
                price_yearly_cents=10000,
                currency="usd",
                features={"risk_analysis": True, "pdf_extraction": True},
                limits={"searches_per_day": 10000, "risk_analyses_per_month": 1000},
            )
            session.add(plan)
            await session.commit()
            await session.refresh(plan)
            sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                status=SubscriptionStatus.active,
                billing_period=BillingPeriod.monthly,
            )
            session.add(sub)
            await session.commit()
            await session.refresh(user)
        return user

    return _make


@pytest.fixture
def auth_headers():
    def _headers(user: User) -> dict[str, str]:
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        token = create_access_token(user.id, role_str, user.password_version)
        return {"Authorization": f"Bearer {token}"}

    return _headers
