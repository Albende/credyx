"""Database-backed cache helpers for company + filings.

Spec: cache registry data 7d, filings 30d. On cache hit, return cached with
`last_fetched_at`. Force-refresh available.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.config import get_settings
from apps.api.app.db import Company as CompanyRow
from apps.api.app.db import FinancialFiling as FilingRow
from packages.shared.models import CompanyDetails, FinancialFiling, IdentifierType


async def upsert_company(
    session: AsyncSession,
    details: CompanyDetails,
) -> CompanyRow:
    primary = (
        details.identifiers[0]
        if details.identifiers
        else None
    )
    primary_type = primary.type.value if primary else "OTHER"
    primary_value = primary.value if primary else details.id

    stmt = (
        pg_insert(CompanyRow)
        .values(
            normalized_name=details.name.lower().strip()[:512],
            country=details.country.upper()[:2],
            primary_identifier_type=primary_type,
            primary_identifier_value=primary_value,
            all_identifiers={i.type.value: i.value for i in details.identifiers},
            registry_data=json.loads(details.model_dump_json()),
            last_fetched_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            index_elements=[CompanyRow.country, CompanyRow.primary_identifier_value],
            set_={
                "normalized_name": details.name.lower().strip()[:512],
                "all_identifiers": {i.type.value: i.value for i in details.identifiers},
                "registry_data": json.loads(details.model_dump_json()),
                "last_fetched_at": datetime.now(timezone.utc),
            },
        )
        .returning(CompanyRow)
    )
    result = await session.execute(stmt)
    row = result.scalar_one()
    await session.commit()
    return row


async def get_cached_company(
    session: AsyncSession,
    country: str,
    identifier_value: str,
    *,
    force_refresh: bool = False,
) -> CompanyRow | None:
    if force_refresh:
        return None
    settings = get_settings()
    stmt = select(CompanyRow).where(
        CompanyRow.country == country.upper(),
        CompanyRow.primary_identifier_value == identifier_value,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if not row:
        return None
    if row.last_fetched_at < datetime.now(timezone.utc) - timedelta(seconds=settings.company_cache_ttl_seconds):
        return None  # stale
    return row


async def upsert_filings(
    session: AsyncSession,
    company_id: UUID,
    filings: list[FinancialFiling],
) -> None:
    if not filings:
        return
    # Easiest correctness: clear & re-insert; cheap enough at this volume.
    from sqlalchemy import delete
    await session.execute(delete(FilingRow).where(FilingRow.company_id == company_id))
    for f in filings:
        session.add(
            FilingRow(
                company_id=company_id,
                year=f.year,
                type=f.type.value,
                period_end=datetime.combine(f.period_end, datetime.min.time()) if f.period_end else None,
                currency=f.currency,
                structured_data=f.structured_data,
                document_url=f.document_url,
                document_format=f.document_format,
                source_url=f.source_url,
            )
        )
    await session.commit()


async def get_cached_filings(
    session: AsyncSession,
    company_id: UUID,
) -> list[FilingRow]:
    stmt = select(FilingRow).where(FilingRow.company_id == company_id).order_by(FilingRow.year.desc())
    return list((await session.execute(stmt)).scalars())
