"""DB roundtrip: insert ingested rows, search by name fragment.

Marked `integration` because it needs a real Postgres with pg_trgm. Skips
gracefully if DATABASE_URL isn't reachable, so `pytest -m "not integration"`
keeps unit-test runs fast.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.app.db import Base, IngestedCompany
from packages.ingestion.fts import search_ingested
from packages.ingestion.sources.be_kbo import BEKboSource

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def session() -> AsyncSession:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://creditlens:creditlens@localhost:5432/creditlens",
        ),
    )
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("DELETE FROM ingested_companies WHERE country = 'BE'"))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Postgres not available: {exc}")
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_and_search_roundtrip(session: AsyncSession) -> None:
    source = BEKboSource(data_path=FIXTURES / "enterprise.csv")
    count = await source.run(session)
    assert count == 3

    matches = await search_ingested(session, country="BE", name="acme bru", limit=5)
    assert any(m.name == "Acme Brussels SA" for m in matches)

    # Re-ingest should upsert, not duplicate.
    count2 = await source.run(session)
    assert count2 == 3
    n = (await session.execute(
        text("SELECT COUNT(*) FROM ingested_companies WHERE country='BE'")
    )).scalar_one()
    assert n == 3


@pytest.mark.asyncio
async def test_search_unknown_returns_empty(session: AsyncSession) -> None:
    matches = await search_ingested(session, country="BE", name="zzzzz nothing", limit=5)
    assert matches == []
