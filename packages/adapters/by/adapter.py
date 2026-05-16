"""Belarus adapter — EGR (Единый государственный регистр).

Source coverage:

* https://egr.gov.by/api/v2/egr/getShortInfoByRegNum/{unp} — combined
  short record (name, legal form, status, registration date).
* https://egr.gov.by/api/v2/egr/getBaseInfoByRegNum/{unp} — base info
  fallback when the short endpoint omits a status or reg-date field.
* https://egr.gov.by/api/v2/egr/getAddressByRegNum/{unp} — registered
  legal address.
* https://egr.gov.by/api/v2/egr/getJurNamesByJurNamePart/{name} — free
  name search; returns up to a few hundred matches.
* https://www.nalog.gov.by/ — Ministry of Taxes & Duties; UNP validator
  exposed only through an interactive web form, not used here.

The portal is government-run, publicly accessible, free, and unauthenticated.
JSON responses come back UTF-8 with Cyrillic field values. No financial
statements are published anywhere centrally: Belarusian LLCs / OAOs file
annual accounts with the MoF / Belstat but neither agency exposes a free
per-company query. `fetch_financials` therefore returns `[]` — never
fabricates numbers.

Identifier:
- UNP (Учетный номер плательщика / Account number of the payer) — 9
  digits. Same number serves as the tax ID and the EGR registration
  number, so the adapter accepts it under both `VAT` and `COMPANY_NUMBER`.
  Some sources prefix it with `BY`; we strip it.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
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

_UNP_RE = re.compile(r"^\d{9}$")

# Belaruskali OAO — long-lived, large taxpayer; safe liveness probe.
_HEALTH_PROBE_UNP = "600122610"


def _normalize_unp(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("BY"):
        cleaned = cleaned[2:]
    if not _UNP_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Belarus UNP must be exactly 9 digits, got: {value}"
        )
    return cleaned


def _parse_by_date(value: str | None) -> date | None:
    """EGR renders dates as ISO YYYY-MM-DD or DD.MM.YYYY depending on field."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _first_str(obj: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return None


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    """EGR endpoints reply either with a single object or a list."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "items", "records"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        return [payload]
    return []


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    # Cyrillic tokens for "operating / acting / liquidated".
    if any(t in low for t in ("действ", "зарегистрир", "active")):
        return "active"
    if any(
        t in low
        for t in ("ликвидир", "прекращ", "исключ", "приостан", "liquidated")
    ):
        return "inactive"
    return raw.strip() or None


def _extract_name(record: dict[str, Any]) -> str | None:
    # The EGR short/jur-names endpoint nests the legal name under varying
    # keys depending on entity type; legal entities use `vnaimp`/`vfn`,
    # sole proprietors use `vfio`. We try all known variants.
    candidates = (
        "vnaim",
        "vnaimk",
        "vnaimp",
        "vn",
        "vfn",
        "vfio",
        "name",
        "fullName",
        "shortName",
    )
    direct = _first_str(record, candidates)
    if direct:
        return direct
    for nested_key in ("jurName", "ip", "company", "uniqueName"):
        nested = record.get(nested_key)
        if isinstance(nested, dict):
            v = _first_str(nested, candidates)
            if v:
                return v
    return None


def _extract_status(record: dict[str, Any]) -> str | None:
    return _first_str(
        record,
        (
            "vnaimsostgo",
            "vnsost",
            "nsi00219vnaim",
            "status",
            "state",
        ),
    )


def _extract_legal_form(record: dict[str, Any]) -> str | None:
    return _first_str(
        record,
        (
            "vnaimop",
            "vnopfp",
            "vnopf",
            "nsi00214vnaim",
            "legalForm",
        ),
    )


def _extract_reg_date(record: dict[str, Any]) -> str | None:
    return _first_str(
        record,
        (
            "dregdate",
            "dreg",
            "registrationDate",
            "datereg",
            "datereg_full",
        ),
    )


def _extract_address(record: dict[str, Any]) -> str | None:
    direct = _first_str(record, ("vpadres", "vadres", "address", "fullAddress"))
    if direct:
        return direct
    parts = []
    for key in ("vnp", "vnpoch", "vname", "vstreet", "vhouse", "vroom"):
        v = record.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return ", ".join(parts) or None


class BYAdapter(CountryAdapter):
    country_code = "BY"
    country_name = "Belarus"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://egr.gov.by"
    SHORT_INFO_PATH = "/api/v2/egr/getShortInfoByRegNum/{unp}"
    BASE_INFO_PATH = "/api/v2/egr/getBaseInfoByRegNum/{unp}"
    ADDRESS_PATH = "/api/v2/egr/getAddressByRegNum/{unp}"
    JUR_NAMES_PATH = "/api/v2/egr/getJurNamesByREGNUM/{unp}"
    NAME_SEARCH_PATH = "/api/v2/egr/getJurNamesByJurNamePart/{name}"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
                "Accept-Language": "ru,be;q=0.9,en;q=0.5",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(
                    client,
                    self.SHORT_INFO_PATH.format(unp=_HEALTH_PROBE_UNP),
                )
                if resp.status_code >= 500:
                    raise RuntimeError(f"egr.gov.by HTTP {resp.status_code}")
                # The portal returns 200 with a JSON body for known UNPs.
                payload = resp.json() if resp.content else None
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        records = _records_from_payload(payload) if payload else []
        if not records or not _extract_name(records[0]):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={
                    "search": True,
                    "lookup": True,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "EGR responded but probe UNP returned no name; the JSON "
                    "schema may have changed."
                ),
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={
                "search": True,
                "lookup": True,
                "financials": False,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup + name search via egr.gov.by JSON API. "
                "Financial statements not centrally published."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        from urllib.parse import quote

        query = name.strip()
        if not query:
            return []
        # EGR embeds the search term in the URL path. quote() preserves
        # Cyrillic letters but encodes spaces / reserved characters which
        # the portal otherwise rejects with a 400.
        path = self.NAME_SEARCH_PATH.format(name=quote(query, safe=""))
        async with self._client() as client:
            resp = await get_with_retry(client, path)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json() if resp.content else None

        records = _records_from_payload(payload)
        matches: list[CompanyMatch] = []
        for rec in records[:limit]:
            unp = _first_str(rec, ("ngrn", "regnum", "regNum", "ngosregnum"))
            company_name = _extract_name(rec)
            if not unp or not company_name:
                continue
            try:
                unp_n = _normalize_unp(str(unp))
            except InvalidIdentifierError:
                continue
            matches.append(
                CompanyMatch(
                    id=unp_n,
                    name=company_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=unp_n,
                            label="UNP",
                        )
                    ],
                    status=_classify_status(_extract_status(rec)),
                    source_url=f"{self.BASE_URL}/egr/?regnum={unp_n}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Belarus adapter supports VAT or COMPANY_NUMBER (UNP), got {id_type}"
            )
        unp = _normalize_unp(value)

        async with self._client() as client:
            short_resp = await get_with_retry(
                client, self.SHORT_INFO_PATH.format(unp=unp)
            )
            if short_resp.status_code == 404:
                return None
            short_resp.raise_for_status()
            short_payload = short_resp.json() if short_resp.content else None

            # Address lives on a separate endpoint; failures here shouldn't
            # poison the lookup, so we tolerate non-200 silently.
            address_payload: Any = None
            try:
                addr_resp = await get_with_retry(
                    client, self.ADDRESS_PATH.format(unp=unp)
                )
                if addr_resp.status_code == 200 and addr_resp.content:
                    address_payload = addr_resp.json()
            except Exception as exc:
                logger.debug("BY address fetch failed for %s: %s", unp, exc)

        records = _records_from_payload(short_payload)
        if not records:
            return None
        record = records[0]
        name = _extract_name(record)
        if not name:
            return None

        address = None
        if address_payload is not None:
            addr_records = _records_from_payload(address_payload)
            if addr_records:
                address = _extract_address(addr_records[0])

        return CompanyDetails(
            id=unp,
            name=name,
            country=self.country_code,
            legal_form=_extract_legal_form(record),
            status=_classify_status(_extract_status(record)),
            incorporation_date=_parse_by_date(_extract_reg_date(record)),
            registered_address=address,
            capital_amount=None,
            capital_currency="BYN",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=unp,
                    label="UNP",
                ),
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=unp,
                    label="UNP (VAT)",
                ),
            ],
            raw={
                "source": "egr.gov.by",
                "short": record,
                "address": address_payload,
            },
            source_url=f"{self.BASE_URL}/egr/?regnum={unp}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Validate identifier shape so callers get a clear error before we
        # commit to a network round-trip — but Belarus publishes no central
        # free filings dataset, so the answer is always an empty list.
        _normalize_unp(company_id)
        return []
