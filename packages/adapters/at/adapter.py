"""Austria adapter — JustizOnline Firmenbuch + GLEIF/ESEF + VIES.

Three free, key-free sources cover the full contract:

- **JustizOnline Firmenbuch** (https://justizonline.gv.at/jop/service/fba) —
  the Ministry of Justice business-register portal exposes a public JSON API
  behind its free "Firmenbuchabfrage" search. ``/fba/search?term=`` fuzzy-matches
  by company name or Firmenbuchnummer and returns the FN, legal status, seat and
  an internal id; ``/fba/{id}`` returns the free basic extract (name, legal form,
  registered address). The full/historical extract and the filed documents behind
  it are paid (€4–€8) and need no login for the basic data used here.
- **GLEIF + XBRL Filings Index** — Austrian Firmenbuchnummern appear in GLEIF
  golden-copy records as ``entity.registeredAs``, giving an FN → LEI bridge. Every
  Austria-domiciled listed issuer files an iXBRL/ESEF annual report to
  https://filings.xbrl.org, keyed by LEI, with a downloadable report package.
- **VIES** (https://ec.europa.eu/taxation_customs/vies) — validates an Austrian
  UID. Austria is in the privacy-restricted group (AT/DE/ES/CY): VIES returns the
  validity flag only, never name/address, so VAT lookup is a weaker signal than
  the FN path.

Identifier scope:
- COMPANY_NUMBER → Firmenbuchnummer, digits (1–6) + optional check letter
  ("FN 93363 z", "93363z", "93363 Z" all valid); canonical form ``<digits><letter>``.
- VAT            → "ATU" + 8 digits.

Capabilities:
- search_by_name                       → JustizOnline FBA fuzzy search.
- lookup_by_identifier(COMPANY_NUMBER) → JustizOnline FBA basic extract.
- lookup_by_identifier(VAT)            → VIES validity signal.
- fetch_financials                     → ESEF annual reports for the issuer's LEI.

Financials are limited to LEI-holding / listed issuers (the free reality for
Austria — filed SME accounts sit behind paid Firmenbuch documents). We never
fabricate registry or financial data: unmatched lookups return ``None`` and a
company with no ESEF filings returns an empty list.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

# Firmenbuchnummer: digits (1–6) + optional single check letter. Stored canonical
# form is "<digits><letter>" (no spaces, lower-case letter), e.g. "93363z".
_FN_RE = re.compile(r"^(\d{1,6})([a-z])?$")

# Austrian VAT (UID) — "U" + 8 digits. Canonical form omits the "AT" prefix
# because VIES wants the country code separately.
_UID_RE = re.compile(r"^U\d{8}$")

_LEI_RE = re.compile(r"^[A-Z0-9]{18}\d{2}$")

_VIES_ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:checkVat>
      <urn:countryCode>{cc}</urn:countryCode>
      <urn:vatNumber>{vat}</urn:vatNumber>
    </urn:checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""
_VIES_NS = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "vies": "urn:ec.europa.eu:taxud:vies:services:checkVat:types",
}


def _normalize_fn(value: str) -> str:
    """Normalize a Firmenbuchnummer to ``<digits><letter?>`` lower-case.

    Accepts forms like ``"FN 93363 z"``, ``"93363z"``, ``"93363 Z"``.
    """
    cleaned = value.strip().lower().replace("\xa0", " ")
    if cleaned.startswith("fn"):
        cleaned = cleaned[2:].strip()
    cleaned = cleaned.replace(" ", "").replace("-", "")
    if not _FN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Austrian Firmenbuchnummer must be digits + optional check letter: {value}"
        )
    return cleaned


def _normalize_uid(value: str) -> str:
    """Normalize an Austrian VAT (UID) to ``U########`` (no "AT" prefix)."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "").replace("-", "")
    if cleaned.startswith("ATU"):
        cleaned = cleaned[2:]
    elif cleaned.startswith("AT"):
        cleaned = cleaned[2:]
    if cleaned.isdigit() and len(cleaned) == 8:
        cleaned = "U" + cleaned
    if not _UID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Austrian VAT (UID) must be 'U' + 8 digits, got: {value}"
        )
    return cleaned


class ATAdapter(CountryAdapter):
    country_code = "AT"
    country_name = "Austria"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    FBA_SEARCH = "https://justizonline.gv.at/jop/service/fba/search"
    FBA_DETAIL = "https://justizonline.gv.at/jop/service/fba"
    FBA_WEB = "https://justizonline.gv.at/jop/web/firmenbuchabfrage"
    GLEIF_URL = "https://api.gleif.org/api/v1/lei-records"
    FILINGS_BASE = "https://filings.xbrl.org"
    FILINGS_API = "https://filings.xbrl.org/api/filings"
    VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Search + FN lookup via the free JustizOnline Firmenbuch JSON API; "
            "VAT via VIES (AT redacts name/address); financials via GLEIF FN→LEI "
            "and the ESEF filings.xbrl.org index. All key-free; filed financials "
            "cover LEI-holding / listed issuers only."
        )
        try:
            result = await self._fba_search("OMV Aktiengesellschaft", limit=1)
        except httpx.HTTPError as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"{notes} JustizOnline probe failed: {str(exc)[:120]}",
            )
        status = AdapterStatus.OK if result else AdapterStatus.DEGRADED
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        companies = await self._fba_search(name, limit=limit)
        matches: list[CompanyMatch] = []
        for c in companies:
            match = _company_to_match(c)
            if match:
                matches.append(match)
        return matches[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_fn(value)
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        raise InvalidIdentifierError(
            f"AT supports COMPANY_NUMBER (FN) or VAT (UID), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        lei = await self._resolve_lei(company_id)
        if lei is None:
            return []
        filings = await self._esef_filings(lei)
        best_by_year: dict[int, tuple[int, date, dict[str, Any]]] = {}
        for attrs in filings:
            period_end = _parse_iso_date(attrs.get("period_end"))
            if period_end is None:
                continue
            idx = _package_index(attrs.get("package_url") or "")
            current = best_by_year.get(period_end.year)
            if current is None or idx < current[0]:
                best_by_year[period_end.year] = (idx, period_end, attrs)
        ordered = sorted(best_by_year.values(), key=lambda t: t[1], reverse=True)
        out: list[FinancialFiling] = []
        for _, period_end, attrs in ordered[: max(1, years)]:
            landing = attrs.get("viewer_url") or attrs.get("package_url")
            out.append(
                FinancialFiling(
                    company_id=company_id,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="EUR",
                    structured_data=None,
                    document_url=f"{self.FILINGS_BASE}{attrs['package_url']}",
                    document_format="xbrl",
                    source_url=f"{self.FILINGS_BASE}{landing}",
                )
            )
        return out

    async def _lookup_by_fn(self, value: str) -> CompanyDetails | None:
        fn = _normalize_fn(value)
        companies = await self._fba_search(fn, limit=10)
        internal_id = next(
            (c["id"] for c in companies if (c.get("fnr") or "").lower() == fn),
            None,
        )
        if internal_id is None:
            return None
        detail = await self._fba_detail(internal_id)
        if detail is None:
            return None
        legal_form = (detail.get("legalForm") or {}).get("name")
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=fn, label="Firmenbuchnummer"
            )
        ]
        return CompanyDetails(
            id=fn,
            name=(detail.get("name") or "").strip() or fn,
            country="AT",
            legal_form=legal_form,
            status=_map_status(detail.get("status")),
            registered_address=_format_fba_address(detail.get("address")),
            capital_currency="EUR",
            identifiers=identifiers,
            raw={"firmenbuch": detail},
            source_url=f"{self.FBA_WEB}/{internal_id}",
        )

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        uid = _normalize_uid(value)
        vies = await self._vies_check(uid)
        if vies is None or not vies.get("valid"):
            return None
        name = (vies.get("name") or "").strip()
        address = (vies.get("address") or "").strip()
        return CompanyDetails(
            id=f"AT{uid}",
            name=name or f"AT{uid}",
            country="AT",
            status="active",
            registered_address=address or None,
            capital_currency="EUR",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=f"AT{uid}", label="UID"),
            ],
            raw={"vies": vies},
            source_url="https://ec.europa.eu/taxation_customs/vies/",
        )

    async def _resolve_lei(self, company_id: str) -> str | None:
        candidate = company_id.strip().upper()
        if _LEI_RE.match(candidate):
            return candidate
        fn = _normalize_fn(company_id)
        records = await self._gleif_query(
            {
                "filter[entity.registeredAs]": fn,
                "filter[entity.legalAddress.country]": "AT",
            }
        )
        for rec in records:
            registered_as = (
                ((rec.get("attributes") or {}).get("entity") or {}).get("registeredAs")
                or ""
            ).strip().lower()
            if registered_as == fn:
                return (rec.get("attributes") or {}).get("lei")
        return records[0]["attributes"]["lei"] if len(records) == 1 else None

    async def _fba_search(self, term: str, *, limit: int) -> list[dict[str, Any]]:
        params = {"term": term, "size": str(min(max(limit, 1), 50)), "page": "0"}
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/json"}
        ) as client:
            resp = await get_with_retry(client, self.FBA_SEARCH, params=params)
        if resp.status_code != 200:
            return []
        try:
            return resp.json().get("companies") or []
        except ValueError:
            return []

    async def _fba_detail(self, internal_id: str) -> dict[str, Any] | None:
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/json"}
        ) as client:
            resp = await get_with_retry(client, f"{self.FBA_DETAIL}/{internal_id}")
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    async def _gleif_query(self, params: dict[str, str]) -> list[dict[str, Any]]:
        async with build_http_client(
            timeout=30.0, headers={"Accept": "application/vnd.api+json"}
        ) as client:
            try:
                resp = await get_with_retry(client, self.GLEIF_URL, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        try:
            return resp.json().get("data") or []
        except ValueError:
            return []

    async def _esef_filings(self, lei: str) -> list[dict[str, Any]]:
        params = {
            "filter": f'[{{"name":"entity.identifier","op":"eq","val":"{lei}"}}]',
            "page[size]": "100",
        }
        async with build_http_client(
            timeout=40.0, headers={"Accept": "application/vnd.api+json"}
        ) as client:
            try:
                resp = await get_with_retry(client, self.FILINGS_API, params=params)
            except httpx.HTTPError:
                return []
        if resp.status_code != 200:
            return []
        try:
            data = resp.json().get("data") or []
        except ValueError:
            return []
        return [
            attrs
            for item in data
            if (attrs := item.get("attributes"))
            and attrs.get("period_end")
            and attrs.get("package_url")
        ]

    async def _vies_check(self, uid: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="AT", vat=uid)
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        try:
            async with build_http_client(timeout=30.0, headers=headers) as client:
                resp = await client.post(self.VIES_URL, content=envelope)
                if resp.status_code != 200:
                    return None
                return _parse_vies_response(resp.text)
        except httpx.HTTPError:
            return None


def _map_status(raw: str | None) -> str | None:
    if not raw:
        return None
    mapping = {"ACTIVE": "active", "DELETED": "dissolved", "HISTORICAL": "historical"}
    return mapping.get(raw.upper(), raw.lower())


def _format_fba_address(address: dict[str, Any] | None) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    if address.get("street"):
        parts.append(str(address["street"]).strip())
    zip_city = " ".join(
        str(address[k]).strip() for k in ("zipCode", "city") if address.get(k)
    )
    if zip_city:
        parts.append(zip_city)
    return ", ".join(p for p in parts if p) or None


def _package_index(package_url: str) -> int:
    parts = package_url.strip("/").split("/")
    if len(parts) >= 5 and parts[4].isdigit():
        return int(parts[4])
    return 0


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _company_to_match(c: dict[str, Any]) -> CompanyMatch | None:
    fnr = (c.get("fnr") or "").strip().lower()
    name = (c.get("name") or "").strip()
    if not fnr or not name:
        return None
    internal_id = c.get("id")
    source_url = (
        f"{ATAdapter.FBA_WEB}/{internal_id}" if internal_id else ATAdapter.FBA_WEB
    )
    return CompanyMatch(
        id=fnr,
        name=name,
        country="AT",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=fnr, label="Firmenbuchnummer"
            )
        ],
        address=(c.get("domicile") or "").strip() or None,
        status=_map_status(c.get("status")),
        source_url=source_url,
    )


def _parse_vies_response(xml_text: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    body = root.find("soap:Body", _VIES_NS)
    if body is None:
        return None
    fault = body.find("soap:Fault", _VIES_NS)
    if fault is not None:
        return {"valid": False, "fault": (fault.findtext("faultstring") or "").strip()}
    resp = body.find("vies:checkVatResponse", _VIES_NS)
    if resp is None:
        return None
    valid = (
        resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or ""
    ).strip().lower() == "true"
    name = (resp.findtext("vies:name", default="", namespaces=_VIES_NS) or "").strip()
    address = (
        resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    ).strip()
    if name == "---":
        name = ""
    if address == "---":
        address = ""
    return {
        "valid": valid,
        "name": name,
        "address": address,
        "checked_at": datetime.utcnow().isoformat(),
    }
