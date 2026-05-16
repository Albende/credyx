"""Postgres full-text / trigram search over `ingested_companies`.

Adapters that lack a per-company API call (BE KBO, UA YeDR, LV UR, IL CKAN)
back their `search_by_name` with `search_ingested`.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.ingestion.sources._base import normalize_name
from packages.shared.models import CompanyMatch, IdentifierType, RegistryIdentifier

logger = logging.getLogger(__name__)

SIMILARITY_FLOOR = 0.2  # pg_trgm default threshold; raise to tighten matches


async def search_ingested(
    session: AsyncSession,
    *,
    country: str,
    name: str,
    limit: int = 10,
) -> list[CompanyMatch]:
    """Search ingested_companies using pg_trgm similarity.

    Returns a list of `CompanyMatch` ordered by descending similarity.
    """
    q = normalize_name(name)
    if not q:
        return []
    country_code = country.upper()[:2]
    stmt = text(
        """
        SELECT source_id, name, country, status, address, identifiers,
               similarity(name_normalized, :q) AS score
        FROM ingested_companies
        WHERE country = :country
          AND name_normalized %% :q
          AND similarity(name_normalized, :q) >= :floor
        ORDER BY score DESC, name ASC
        LIMIT :lim
        """
    ).bindparams(
        bindparam("q", value=q),
        bindparam("country", value=country_code),
        bindparam("floor", value=SIMILARITY_FLOOR),
        bindparam("lim", value=limit),
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [_row_to_match(r) for r in rows]


def _row_to_match(row: dict[str, Any]) -> CompanyMatch:
    identifiers: list[RegistryIdentifier] = []
    for ident in row.get("identifiers") or []:
        try:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType(ident.get("type", "OTHER")),
                    value=str(ident["value"]),
                    label=ident.get("label"),
                )
            )
        except (KeyError, ValueError):
            continue
    return CompanyMatch(
        id=row["source_id"],
        name=row["name"],
        country=row["country"],
        status=row.get("status"),
        address=row.get("address"),
        identifiers=identifiers,
    )
