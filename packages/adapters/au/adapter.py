"""Australia adapter — ABN Lookup (Australian Business Register).

ABR offers a free JSON-over-JSONP web service. Auth is a GUID issued at
https://abr.business.gov.au/Tools/WebServices and passed as a query param.

The registry covers ~10M active ABNs and ACNs. It does NOT publish
financial statements: ASIC sells filings per document and there is no
free official source. `fetch_financials` therefore raises
`AdapterNotImplementedError` — per rule #1, never invent numbers.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.DOTALL)
_ABN_RE = re.compile(r"^\d{11}$")
_ACN_RE = re.compile(r"^\d{9}$")
_ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)


def _strip_jsonp(text: str) -> dict[str, Any]:
    """Unwrap `callback({...});` and return the parsed JSON object."""
    match = _JSONP_RE.match(text.strip())
    payload = match.group(1) if match else text.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"ABR returned unparseable JSONP: {exc}") from exc


def _normalize_abn(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip().upper()).removeprefix("AU")
    if not _ABN_RE.match(cleaned):
        raise InvalidIdentifierError(f"AU ABN must be 11 digits: {value}")
    return cleaned


def _normalize_acn(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip())
    if not _ACN_RE.match(cleaned):
        raise InvalidIdentifierError(f"AU ACN must be 9 digits: {value}")
    return cleaned


def _is_valid_abn_checksum(abn: str) -> bool:
    """ABR's published ABN check-digit algorithm.

    Subtract 1 from the first digit, multiply each digit by its weight,
    sum, and verify the total is divisible by 89.
    """
    if not _ABN_RE.match(abn):
        return False
    digits = [int(c) for c in abn]
    digits[0] -= 1
    total = sum(d * w for d, w in zip(digits, _ABN_WEIGHTS))
    return total % 89 == 0


def _coalesce_name(payload: dict[str, Any]) -> str:
    entity_name = payload.get("EntityName")
    if entity_name:
        return entity_name
    business_names = payload.get("BusinessName") or []
    if isinstance(business_names, list) and business_names:
        first = business_names[0]
        if isinstance(first, dict):
            return first.get("OrganisationName", "") or ""
        return str(first)
    trading_names = payload.get("MainTradingName") or payload.get("TradingName") or []
    if isinstance(trading_names, list) and trading_names:
        first = trading_names[0]
        if isinstance(first, dict):
            return first.get("OrganisationName", "") or ""
        return str(first)
    return ""


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class AUAdapter(CountryAdapter):
    country_code = "AU"
    country_name = "Australia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = True
    api_key_env = "AU_ABN_LOOKUP_GUID"
    rate_limit_per_minute = 120

    BASE_URL = "https://abr.business.gov.au/json"
    PUBLIC_LOOKUP_URL = "https://abr.business.gov.au/ABN/View"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv(self.api_key_env)

    def _client(self):
        return build_http_client(base_url=self.BASE_URL)

    async def health_check(self) -> AdapterHealth:
        if not self.api_key:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    f"Set {self.api_key_env} (free GUID from "
                    "https://abr.business.gov.au/Tools/WebServices)."
                ),
            )
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    "/AbnDetails.aspx",
                    params={
                        "abn": "49004028077",
                        "guid": self.api_key,
                        "callback": "callback",
                    },
                )
                resp.raise_for_status()
                _strip_jsonp(resp.text)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Financials not available: ASIC charges per document.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                "/MatchingNames.aspx",
                params={
                    "name": name,
                    "maxResults": str(limit),
                    "guid": self.api_key,
                    "callback": "callback",
                },
            )
            resp.raise_for_status()
            data = _strip_jsonp(resp.text)

        items = data.get("Names") or []
        matches: list[CompanyMatch] = []
        for item in items[:limit]:
            abn = (item.get("Abn") or "").replace(" ", "")
            if not abn:
                continue
            identifiers = [
                RegistryIdentifier(type=IdentifierType.VAT, value=abn, label="ABN")
            ]
            acn = item.get("Acn")
            if acn:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=str(acn),
                        label="ACN",
                    )
                )
            state = item.get("State")
            postcode = item.get("Postcode")
            address_bits = [b for b in (state, postcode) if b]
            matches.append(
                CompanyMatch(
                    id=abn,
                    name=item.get("Name", "") or "",
                    country=self.country_code,
                    identifiers=identifiers,
                    address=", ".join(address_bits) or None,
                    status="active" if item.get("IsCurrentIndicator") == "Y" else None,
                    source_url=f"{self.PUBLIC_LOOKUP_URL}/{abn}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if not self.api_key:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        if id_type == IdentifierType.VAT:
            abn = _normalize_abn(value)
            if not _is_valid_abn_checksum(abn):
                raise InvalidIdentifierError(f"AU ABN failed checksum: {value}")
            params = {"abn": abn, "guid": self.api_key, "callback": "callback"}
            endpoint = "/AbnDetails.aspx"
        elif id_type == IdentifierType.COMPANY_NUMBER:
            acn = _normalize_acn(value)
            params = {"acn": acn, "guid": self.api_key, "callback": "callback"}
            endpoint = "/AcnDetails.aspx"
        else:
            raise InvalidIdentifierError(
                f"AU supports VAT (ABN) or COMPANY_NUMBER (ACN), got {id_type}"
            )

        async with self._client() as client:
            resp = await get_with_retry(client, endpoint, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = _strip_jsonp(resp.text)

        if data.get("Message"):
            logger.info("ABR returned message for %s=%s: %s", id_type, value, data["Message"])
        abn = (data.get("Abn") or "").replace(" ", "")
        if not abn:
            return None
        return _details_from_payload(data, abn)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raise AdapterNotImplementedError(
            "AU financials require paid ASIC document purchase — Phase 2."
        )


def _details_from_payload(data: dict[str, Any], abn: str) -> CompanyDetails:
    name = _coalesce_name(data)
    acn = data.get("Acn") or data.get("AsicNumber")
    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(type=IdentifierType.VAT, value=abn, label="ABN")
    ]
    if acn:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=str(acn),
                label="ACN",
            )
        )

    addr_parts = [
        data.get("AddressState"),
        data.get("AddressPostcode"),
    ]
    address = ", ".join(p for p in addr_parts if p) or None

    inc_date = _parse_iso_date(data.get("EntityTypeEffectiveFrom"))
    status_text = data.get("EntityStatusCode") or data.get("AbnStatus")
    legal_form = data.get("EntityType")
    if isinstance(legal_form, dict):
        legal_form = legal_form.get("EntityDescription")

    return CompanyDetails(
        id=abn,
        name=name,
        country="AU",
        legal_form=legal_form,
        status=status_text,
        incorporation_date=inc_date,
        registered_address=address,
        capital_currency="AUD",
        identifiers=identifiers,
        raw=data,
        source_url=f"https://abr.business.gov.au/ABN/View/{abn}",
        fetched_at=datetime.utcnow(),
    )
