"""GLEIF-backed registry access for Saudi Arabia.

GLEIF is free, key-less, and stores each Saudi legal entity's Commercial
Registration number in ``entity.registeredAs`` (registration authority
RA000513 — the Saudi Ministry of Commerce). That gives CreditLens a real
structured registry record keyed on the CR, plus a fulltext name search
that also matches Arabic legal names via their transliterated forms.
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
_ACRONYM_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9 &.\-]{1,40})\)")


async def _get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    async with build_http_client(base_url=_BASE_URL, headers=_HEADERS) as client:
        resp = await get_with_retry(client, path, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


async def search_sa(name: str, limit: int = 10) -> list[CompanyMatch]:
    payload = await _get(
        "/lei-records",
        {
            "filter[fulltext]": name,
            "filter[entity.legalAddress.country]": "SA",
            "page[size]": max(1, min(int(limit), 200)),
            "page[number]": 1,
        },
    )
    records = (payload or {}).get("data") or []
    return [m for m in (_to_match(r) for r in records) if m is not None]


async def lookup_cr(cr: str) -> CompanyDetails | None:
    record = await _record_by_cr(cr)
    if record is None:
        return None
    lei = record.get("id")
    details = await GLEIFClient().lookup_by_lei(str(lei)) if lei else None
    if details is None:
        return None
    if not any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == cr
        for i in details.identifiers
    ):
        details.identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=cr, label="CR Number"
            )
        )
    return details


async def name_variants_for_cr(cr: str) -> list[str]:
    record = await _record_by_cr(cr)
    return _name_variants(record) if record is not None else []


async def _record_by_cr(cr: str) -> dict[str, Any] | None:
    payload = await _get(
        "/lei-records",
        {
            "filter[entity.registeredAs]": cr,
            "filter[entity.legalAddress.country]": "SA",
            "page[size]": 5,
        },
    )
    records = (payload or {}).get("data") or []
    for record in records:
        entity = (record.get("attributes") or {}).get("entity") or {}
        if str(entity.get("registeredAs") or "") == cr:
            return record
    return records[0] if records else None


def _name_variants(record: dict[str, Any]) -> list[str]:
    entity = (record.get("attributes") or {}).get("entity") or {}
    names: list[str] = []
    legal = ((entity.get("legalName") or {}).get("name")) or ""
    if legal:
        names.append(legal)
    for key in ("otherNames", "transliteratedOtherNames"):
        for item in entity.get(key) or []:
            value = (item or {}).get("name")
            if value:
                names.append(value)
    for source in list(names):
        names.extend(_ACRONYM_RE.findall(source))
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.strip().upper()
        if key and key not in seen:
            seen.add(key)
            unique.append(name.strip())
    return unique


def _to_match(record: dict[str, Any]) -> CompanyMatch | None:
    lei = record.get("id")
    entity = (record.get("attributes") or {}).get("entity") or {}
    name = ((entity.get("legalName") or {}).get("name")) or ""
    if not lei or not name:
        return None
    address = entity.get("legalAddress") or {}
    identifiers = [RegistryIdentifier(type=IdentifierType.LEI, value=str(lei))]
    registered_as = entity.get("registeredAs")
    if registered_as:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=str(registered_as),
                label="CR Number",
            )
        )
    status_raw = (entity.get("status") or "").upper()
    return CompanyMatch(
        id=str(lei),
        name=str(name),
        country=(address.get("country") or "SA").upper(),
        identifiers=identifiers,
        address=_format_address(address),
        status="active" if status_raw == "ACTIVE" else (status_raw.lower() or None),
        source_url=f"https://search.gleif.org/#/record/{lei}",
    )


def _format_address(address: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for line in address.get("addressLines") or []:
        if line:
            parts.append(str(line))
    for key in ("city", "region", "postalCode", "country"):
        value = address.get(key)
        if value:
            parts.append(str(value))
    return ", ".join(p.strip() for p in parts if p and p.strip()) or None
