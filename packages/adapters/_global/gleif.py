"""GLEIF (Global Legal Entity Identifier Foundation) client.

Free, no auth, JSON:API spec. https://api.gleif.org/api/v1

Used both as a standalone global lookup and as a fallback when a country
adapter cannot perform name search (raises AdapterNotImplementedError).
"""
from __future__ import annotations

from typing import Any

from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    CompanyDetails,
    CompanyMatch,
    IdentifierType,
    RegistryIdentifier,
)


class GLEIFClient:
    """Async client over the public GLEIF JSON:API.

    Covers ~2M+ legal entities worldwide. Returns CompanyMatch /
    CompanyDetails models so callers don't deal with raw JSON:API.
    """

    BASE_URL = "https://api.gleif.org/api/v1"

    async def search_by_name(
        self,
        *,
        name: str,
        country: str | None = None,
        limit: int = 10,
    ) -> list[CompanyMatch]:
        """Search legal entities by legal name, optionally constrained to a country."""
        params: dict[str, Any] = {
            "filter[entity.legalName]": name,
            "page[size]": max(1, min(int(limit), 200)),
            "page[number]": 1,
        }
        if country:
            params["filter[entity.legalAddress.country]"] = country.upper()

        async with build_http_client(
            base_url=self.BASE_URL,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()

        records = payload.get("data") or []
        matches: list[CompanyMatch] = []
        for record in records:
            match = _record_to_match(record)
            if match:
                matches.append(match)
        return matches

    async def lookup_by_lei(self, lei: str) -> CompanyDetails | None:
        """Fetch full record for a single LEI."""
        lei_clean = lei.strip().upper()
        if not lei_clean:
            return None
        async with build_http_client(
            base_url=self.BASE_URL,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, f"/lei-records/{lei_clean}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()

        record = payload.get("data")
        if not record:
            return None
        return _record_to_details(record)


def _safe_get(obj: Any, *keys: str) -> Any:
    """Walk nested dicts safely. Returns None on any missing key/None value."""
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _format_address(address: dict[str, Any] | None) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    elif isinstance(lines, str) and lines:
        parts.append(lines)
    for key in ("addressNumber", "addressNumberWithinBuilding", "city", "region", "postalCode", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


def _record_to_match(record: dict[str, Any]) -> CompanyMatch | None:
    lei = record.get("id") or _safe_get(record, "attributes", "lei")
    if not lei:
        return None
    attributes = record.get("attributes") or {}
    entity = attributes.get("entity") or {}
    name = _safe_get(entity, "legalName", "name") or ""
    if not name:
        return None
    address = entity.get("legalAddress") or {}
    country = address.get("country") or ""
    status_raw = (entity.get("status") or "").upper()
    status = "active" if status_raw == "ACTIVE" else (status_raw.lower() or None)
    return CompanyMatch(
        id=str(lei),
        name=str(name),
        country=str(country).upper() if country else "",
        identifiers=[RegistryIdentifier(type=IdentifierType.LEI, value=str(lei))],
        address=_format_address(address),
        status=status,
        source_url=f"https://search.gleif.org/#/record/{lei}",
    )


def _record_to_details(record: dict[str, Any]) -> CompanyDetails | None:
    lei = record.get("id") or _safe_get(record, "attributes", "lei")
    if not lei:
        return None
    attributes = record.get("attributes") or {}
    entity = attributes.get("entity") or {}
    name = _safe_get(entity, "legalName", "name") or ""
    if not name:
        return None
    address = entity.get("legalAddress") or {}
    country = (address.get("country") or "").upper()
    status_raw = (entity.get("status") or "").upper()
    status = "active" if status_raw == "ACTIVE" else (status_raw.lower() or None)
    legal_form = _safe_get(entity, "legalForm", "id")

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(type=IdentifierType.LEI, value=str(lei))
    ]
    registration_authority = entity.get("registeredAt") or {}
    other_id = entity.get("registeredAs")
    if other_id:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.OTHER,
                value=str(other_id),
                label=(
                    str(registration_authority.get("id"))
                    if registration_authority.get("id")
                    else "registeredAs"
                ),
            )
        )

    return CompanyDetails(
        id=str(lei),
        name=str(name),
        country=country,
        legal_form=str(legal_form) if legal_form else None,
        status=status,
        registered_address=_format_address(address),
        identifiers=identifiers,
        raw=record,
        source_url=f"https://search.gleif.org/#/record/{lei}",
    )
