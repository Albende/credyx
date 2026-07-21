"""GLEIF-backed registry access for private (non-listed) Turkish companies.

MERSIS itself is gated behind e-Devlet, but GLEIF is free and key-less and
stores each Turkish legal entity's 16-digit MERSIS number in
``entity.registeredAs`` (registration authority RA000560). That gives a
real structured registry record — legal name, MERSIS, address, status,
creation date — for thousands of TR companies that KAP (listed-only)
cannot see, e.g. ETİ GIDA SANAYİ VE TİCARET A.Ş.

Turkish legal names use İ/ı/Ş/Ğ, which the ``fulltext`` filter does not
transliterate — ASCII queries like "ETI GIDA" miss them. GLEIF's
``fuzzycompletions`` endpoint DOES match across the transliteration, so
search runs fulltext first and falls back to fuzzy completions.
"""
from __future__ import annotations

import re
from typing import Any

from packages.adapters._base.http import build_http_client, get_with_retry
from packages.adapters._global.gleif import GLEIFClient
from packages.shared.models import (
    CompanyDetails,
    CompanyMatch,
    IdentifierType,
    RegistryIdentifier,
)

_BASE_URL = "https://api.gleif.org/api/v1"
_HEADERS = {"Accept": "application/vnd.api+json"}
_MERSIS_RE = re.compile(r"^\d{16}$")
_LEI_RE = re.compile(r"^[A-Z0-9]{18}\d{2}$")


def is_lei(value: str) -> bool:
    return bool(_LEI_RE.match(value.strip().upper()))


async def _get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    async with build_http_client(base_url=_BASE_URL, headers=_HEADERS) as client:
        resp = await get_with_retry(client, path, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def search_tr(name: str, limit: int = 10) -> list[CompanyMatch]:
    limit = max(1, min(int(limit), 50))
    payload = await _get(
        "/lei-records",
        {
            "filter[fulltext]": name,
            "filter[entity.legalAddress.country]": "TR",
            "page[size]": limit,
            "page[number]": 1,
        },
    )
    records = (payload or {}).get("data") or []
    if not records:
        records = await _fuzzy_tr_records(name, limit)
    return [m for m in (_to_match(r) for r in records) if m is not None]


async def _fuzzy_tr_records(name: str, limit: int) -> list[dict[str, Any]]:
    payload = await _get(
        "/fuzzycompletions", {"field": "entity.legalName", "q": name}
    )
    leis: list[str] = []
    for item in (payload or {}).get("data") or []:
        rel = ((item.get("relationships") or {}).get("lei-records") or {}).get("data") or {}
        lei = rel.get("id")
        if lei and lei not in leis:
            leis.append(str(lei))
        if len(leis) >= limit:
            break
    if not leis:
        return []
    detail = await _get(
        "/lei-records",
        {"filter[lei]": ",".join(leis), "page[size]": len(leis)},
    )
    records = (detail or {}).get("data") or []
    return [
        r
        for r in records
        if (((r.get("attributes") or {}).get("entity") or {}).get("legalAddress") or {})
        .get("country") == "TR"
    ]


async def lookup_lei(lei: str) -> CompanyDetails | None:
    details = await GLEIFClient().lookup_by_lei(lei.strip().upper())
    if details is None:
        return None
    await _ensure_mersis_identifier(details, lei)
    return details


async def lookup_mersis(mersis: str) -> CompanyDetails | None:
    payload = await _get(
        "/lei-records",
        {
            "filter[entity.registeredAs]": mersis,
            "filter[entity.legalAddress.country]": "TR",
            "page[size]": 5,
        },
    )
    records = (payload or {}).get("data") or []
    record = next(
        (
            r
            for r in records
            if str(((r.get("attributes") or {}).get("entity") or {}).get("registeredAs") or "")
            == mersis
        ),
        records[0] if records else None,
    )
    if record is None:
        return None
    lei = str(record.get("id") or "")
    if not lei:
        return None
    return await lookup_lei(lei)


async def _ensure_mersis_identifier(details: CompanyDetails, lei: str) -> None:
    if any(i.type == IdentifierType.MERSIS for i in details.identifiers):
        return
    payload = await _get(f"/lei-records/{lei.strip().upper()}", {})
    entity = (((payload or {}).get("data") or {}).get("attributes") or {}).get("entity") or {}
    registered_as = str(entity.get("registeredAs") or "")
    if _MERSIS_RE.match(registered_as):
        # GLEIFClient may already carry the number as an untyped identifier.
        details.identifiers = [
            i for i in details.identifiers if i.value != registered_as
        ]
        details.identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.MERSIS, value=registered_as, label="MERSIS"
            )
        )


def _to_match(record: dict[str, Any]) -> CompanyMatch | None:
    lei = record.get("id")
    entity = (record.get("attributes") or {}).get("entity") or {}
    name = ((entity.get("legalName") or {}).get("name")) or ""
    if not lei or not name:
        return None
    address = entity.get("legalAddress") or {}
    identifiers = [RegistryIdentifier(type=IdentifierType.LEI, value=str(lei))]
    registered_as = str(entity.get("registeredAs") or "")
    if _MERSIS_RE.match(registered_as):
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.MERSIS, value=registered_as, label="MERSIS"
            )
        )
    status_raw = (entity.get("status") or "").upper()
    return CompanyMatch(
        id=str(lei),
        name=str(name),
        country="TR",
        identifiers=identifiers,
        address=_format_address(address),
        status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
        source_url=f"https://search.gleif.org/#/record/{lei}",
    )


def _format_address(address: dict[str, Any]) -> str | None:
    parts: list[str] = [str(x) for x in address.get("addressLines") or [] if x]
    for key in ("city", "postalCode"):
        value = address.get(key)
        if value:
            parts.append(str(value))
    return ", ".join(parts) if parts else None
