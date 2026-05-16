"""IngestionSource ABC + the DTO every source emits."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db import IngestedCompany

logger = logging.getLogger(__name__)

# How many DTOs to accumulate before flushing to Postgres. Large enough to
# amortize round-trips, small enough that one bad row doesn't lose much work.
DEFAULT_BATCH_SIZE = 1000


def normalize_name(name: str) -> str:
    """Lowercase + collapse whitespace. Used both at ingest and at query time."""
    return " ".join(name.lower().split())


class IngestedCompanyDTO(BaseModel):
    """In-flight record emitted by a source's parse step."""

    model_config = ConfigDict(extra="ignore")

    country: str = Field(min_length=2, max_length=2)
    source_id: str
    name: str
    status: str | None = None
    address: str | None = None
    identifiers: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def name_normalized(self) -> str:
        return normalize_name(self.name)


class IngestionSource(ABC):
    """One bulk dump from one registry."""

    country_code: str
    name: str
    schedule: str = "daily"  # human-readable; cron set in scheduler

    @abstractmethod
    def download(self, *, since: datetime | None = None) -> AsyncIterator[bytes]:
        """Yield raw bytes from the upstream dump.

        Implementations should stream — do not buffer the whole file in memory.
        For sources that require a manually downloaded file on disk, read the
        path from env and yield its bytes in chunks.
        """

    @abstractmethod
    def parse(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[IngestedCompanyDTO]:
        """Parse raw bytes into DTOs."""

    async def run(self, session: AsyncSession, *, since: datetime | None = None) -> int:
        """Download -> parse -> upsert. Returns number of records ingested."""
        count = 0
        batch: list[dict[str, Any]] = []
        ingest_ts = datetime.now(timezone.utc)
        async for dto in self.parse(self.download(since=since)):
            batch.append(
                {
                    "country": dto.country.upper(),
                    "source_id": dto.source_id,
                    "name": dto.name[:1024],
                    "name_normalized": dto.name_normalized[:1024],
                    "status": dto.status,
                    "address": dto.address,
                    "identifiers": dto.identifiers,
                    "raw": dto.raw,
                    "ingested_at": ingest_ts,
                }
            )
            if len(batch) >= DEFAULT_BATCH_SIZE:
                await _flush(session, batch)
                count += len(batch)
                batch.clear()
        if batch:
            await _flush(session, batch)
            count += len(batch)
        logger.info("ingestion %s/%s upserted %d rows", self.country_code, self.name, count)
        return count


async def _flush(session: AsyncSession, batch: list[dict[str, Any]]) -> None:
    """Upsert one batch with ON CONFLICT (country, source_id) DO UPDATE."""
    if not batch:
        return
    stmt = pg_insert(IngestedCompany).values(batch)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ingested_country_source_id",
        set_={
            "name": stmt.excluded.name,
            "name_normalized": stmt.excluded.name_normalized,
            "status": stmt.excluded.status,
            "address": stmt.excluded.address,
            "identifiers": stmt.excluded.identifiers,
            "raw": stmt.excluded.raw,
            "ingested_at": stmt.excluded.ingested_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
