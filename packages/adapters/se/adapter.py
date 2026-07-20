"""Sweden adapter — Bolagsverket open data + GLEIF/ESEF filings.

Sweden's authoritative business registry is **Bolagsverket
Näringslivsregistret**. Since 3 Feb 2025 Bolagsverket + SCB publish the
company base register as an EU "valuable dataset" (värdefulla
datamängder): free of charge, but the official gateway
(`api.bolagsverket.se`) is fronted by mutual-TLS and requires a
registered client certificate, so it is not usable key-free.

What is freely usable today, with no key and no registration:

- **mackan.eu Bolagsverket proxy** (CC-BY-4.0) — a thin public JSON proxy
  over Bolagsverket's free valuable-datasets API. `/search_name.php`
  full-text searches all ~1.2M registered companies; `/get_data.php`
  returns the authoritative base record (name, legal form, status,
  registered address, SNI codes, registration date, business
  description) for one Organisationsnummer. Data is Bolagsverket's own —
  not a scrape of a ToS-restricted aggregator.
- **GLEIF** — maps an Organisationsnummer to the company's LEI, key-free.
- **filings.xbrl.org** (XBRL International, free, no key) — the public
  repository of every EU-listed company's ESEF/iXBRL annual financial
  report. Yields real, per-company, downloadable report packages for
  Swedish listed issuers (Volvo, Ericsson, H&M, …).
- **VIES** — kept as a VAT-validation fallback for `lookup_by_identifier`
  when the Bolagsverket proxy is unreachable.

`allabolag.se` / `merinfo.se` are deliberately *not* used: their ToS
forbids automated scraping.

Organisationsnummer format: 10 digits, typically printed `XXXXXX-XXXX`.
The 10th digit is a Luhn (mod-10) check digit over the first 9.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

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

_ORGNR_RE = re.compile(r"^\d{10}$")
_VAT_RE = re.compile(r"^\d{12}$")

# AB Volvo — stable, always-valid Organisationsnummer used as a health probe.
_HEALTH_PROBE = "5560125790"

_MACKAN_BASE = "https://mackan.eu/tools/bolagsverket"
_GLEIF_BASE = "https://api.gleif.org/api/v1/lei-records"
_FILINGS_BASE = "https://filings.xbrl.org"

_VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"

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


def _luhn_ok(digits: str) -> bool:
    """Validate a Swedish Organisationsnummer via the Luhn algorithm.

    The 10th digit is the check digit. Walk the first 9 digits left to
    right, doubling every other digit starting at the leftmost. If a
    doubled value exceeds 9, sum its digits. The check digit must make the
    total a multiple of 10.
    """
    if len(digits) != 10 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(digits[:9]):
        n = int(ch)
        if i % 2 == 0:
            doubled = n * 2
            total += doubled if doubled < 10 else doubled - 9
        else:
            total += n
    check = (10 - (total % 10)) % 10
    return check == int(digits[9])


def _normalize_orgnr(value: str) -> str:
    """Normalize a Swedish Org Nr to bare 10 digits.

    Accepts `XXXXXX-XXXX`, plain 10-digit, the legacy 12-digit
    century-prefixed form, and a `SE`/`SE…01` VAT wrapper. Validates Luhn.
    """
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("SE"):
        cleaned = cleaned[2:]
    if len(cleaned) == 12 and cleaned.endswith("01"):
        cleaned = cleaned[:10]
    if not _ORGNR_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Swedish Organisationsnummer must be 10 digits: {value}"
        )
    if not _luhn_ok(cleaned):
        raise InvalidIdentifierError(
            f"Swedish Organisationsnummer Luhn checksum invalid: {value}"
        )
    return cleaned


def _normalize_se_vat(value: str) -> str:
    """Normalize a Swedish VAT number to bare 12 digits.

    SE VAT is `SE` + 10-digit Org Nr + `01`. The first 10 digits must
    Luhn-validate.
    """
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("SE"):
        cleaned = cleaned[2:]
    if len(cleaned) == 10:
        cleaned = f"{cleaned}01"
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Swedish VAT must be SE + 12 digits, got: {value}"
        )
    if not cleaned.endswith("01"):
        raise InvalidIdentifierError(
            f"Swedish VAT must end with '01' suffix: {value}"
        )
    if not _luhn_ok(cleaned[:10]):
        raise InvalidIdentifierError(
            f"Swedish VAT Org Nr portion Luhn checksum invalid: {value}"
        )
    return cleaned


def _hyphenate(orgnr: str) -> str:
    return f"{orgnr[:6]}-{orgnr[6:]}"


def _identifiers(orgnr: str) -> list[RegistryIdentifier]:
    return [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=orgnr,
            label="Organisationsnummer",
        ),
        RegistryIdentifier(
            type=IdentifierType.VAT,
            value=f"SE{orgnr}01",
            label="VAT",
        ),
    ]


class SEAdapter(CountryAdapter):
    country_code = "SE"
    country_name = "Sweden"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        try:
            record = await self._mackan_get_data(_HEALTH_PROBE)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"Bolagsverket proxy probe failed: {str(exc)[:160]}",
            )
        if not record:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Bolagsverket proxy reachable but Volvo lookup returned nothing.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + lookup via Bolagsverket open data (mackan.eu proxy); "
                "financials via GLEIF + filings.xbrl.org ESEF for listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if len(query) < 2:
            return []
        async with build_http_client(timeout=30.0) as client:
            resp = await get_with_retry(
                client, f"{_MACKAN_BASE}/search_name.php", params={"q": query}
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()

        matches: list[CompanyMatch] = []
        for hit in payload.get("results", [])[:limit]:
            orgnr = str(hit.get("orgnr") or "").strip()
            if not _ORGNR_RE.match(orgnr):
                continue
            matches.append(
                CompanyMatch(
                    id=orgnr,
                    name=(hit.get("name") or "").strip() or orgnr,
                    country="SE",
                    identifiers=_identifiers(orgnr),
                    address=(hit.get("city") or "").strip() or None,
                    status="active" if hit.get("active") else "inactive",
                    source_url=f"{_MACKAN_BASE}/get_data.php?orgnr={orgnr}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            orgnr = _normalize_se_vat(value)[:10]
        elif id_type == IdentifierType.COMPANY_NUMBER:
            orgnr = _normalize_orgnr(value)
        else:
            raise InvalidIdentifierError(
                f"SE supports COMPANY_NUMBER (Org Nr) / VAT, got {id_type}"
            )

        record = await self._mackan_get_data(orgnr)
        if record:
            return _details_from_mackan(orgnr, record)

        vies = await self._vies_check(orgnr)
        if not vies or not vies.get("valid"):
            return None
        return CompanyDetails(
            id=orgnr,
            name=(vies.get("name") or "").strip() or orgnr,
            country="SE",
            status="active",
            registered_address=(vies.get("address") or "").strip() or None,
            capital_currency="SEK",
            identifiers=_identifiers(orgnr),
            raw={"vies": vies},
            source_url=None,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        orgnr = _normalize_orgnr(company_id)
        lei = await self._lei_for_orgnr(orgnr)
        if not lei:
            return []
        raw_filings = await self._esef_filings(lei)

        best_by_period: dict[str, dict[str, Any]] = {}
        for f in raw_filings:
            period_end = (f.get("period_end") or "").strip()
            pkg = f.get("package_url") or ""
            if not period_end or not pkg:
                continue
            existing = best_by_period.get(period_end)
            if existing is None or (
                pkg.endswith("-en.zip") and not existing["package_url"].endswith("-en.zip")
            ):
                best_by_period[period_end] = f

        filings: list[FinancialFiling] = []
        for period_end in sorted(best_by_period, reverse=True)[:years]:
            f = best_by_period[period_end]
            end_date = _parse_date(period_end)
            if end_date is None:
                continue
            pkg = f["package_url"]
            viewer = f.get("viewer_url") or f.get("report_url") or pkg
            filings.append(
                FinancialFiling(
                    company_id=orgnr,
                    year=end_date.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=end_date,
                    currency=None,
                    structured_data=None,
                    document_url=f"{_FILINGS_BASE}{pkg}",
                    document_format="xbrl",
                    source_url=f"{_FILINGS_BASE}{viewer}",
                )
            )
        return filings

    async def _mackan_get_data(self, orgnr: str) -> dict[str, Any] | None:
        async with build_http_client(timeout=30.0) as client:
            resp = await get_with_retry(
                client, f"{_MACKAN_BASE}/get_data.php", params={"orgnr": orgnr}
            )
            if resp.status_code in (400, 404):
                return None
            resp.raise_for_status()
            payload = resp.json()
        orgs = payload.get("organisationer") or []
        return orgs[0] if orgs else None

    async def _lei_for_orgnr(self, orgnr: str) -> str | None:
        async with build_http_client(timeout=30.0) as client:
            for registered_as in (_hyphenate(orgnr), orgnr):
                resp = await get_with_retry(
                    client,
                    _GLEIF_BASE,
                    params={"filter[entity.registeredAs]": registered_as},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json().get("data") or []
                if data:
                    return data[0]["attributes"]["lei"]
        return None

    async def _esef_filings(self, lei: str) -> list[dict[str, Any]]:
        query = json.dumps([{"name": "entity.identifier", "op": "eq", "val": lei}])
        async with build_http_client(timeout=40.0) as client:
            resp = await get_with_retry(
                client,
                f"{_FILINGS_BASE}/api/filings",
                params={"filter": query, "page[size]": 100},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json().get("data") or []
        return [row.get("attributes", {}) for row in data]

    async def _vies_check(self, orgnr: str) -> dict[str, Any] | None:
        envelope = _VIES_ENVELOPE.format(cc="SE", vat=f"{orgnr}01")
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        async with build_http_client(timeout=30.0, headers=headers) as client:
            resp = await client.post(_VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _details_from_mackan(orgnr: str, org: dict[str, Any]) -> CompanyDetails:
    name_list = (org.get("organisationsnamn") or {}).get("organisationsnamnLista") or []
    name = next((n.get("namn") for n in name_list if n.get("namn")), None) or orgnr

    legal_form = ((org.get("organisationsform") or {}).get("klartext")) or (
        (org.get("juridiskForm") or {}).get("klartext")
    )

    if org.get("avregistreradOrganisation"):
        status = "deregistered"
    elif ((org.get("verksamOrganisation") or {}).get("kod")) == "NEJ":
        status = "inactive"
    else:
        status = "active"

    incorporation = _parse_date(
        ((org.get("organisationsdatum") or {}).get("registreringsdatum")) or ""
    )

    post = (org.get("postadressOrganisation") or {}).get("postadress") or {}
    address_parts = [
        post.get("coAdress"),
        post.get("utdelningsadress"),
        " ".join(p for p in (post.get("postnummer"), post.get("postort")) if p),
    ]
    registered_address = ", ".join(p.strip() for p in address_parts if p and p.strip()) or None

    sni = (org.get("naringsgrenOrganisation") or {}).get("sni") or []
    nace_codes = [
        code.strip()
        for entry in sni
        if (code := (entry.get("kod") or "")).strip()
    ]

    return CompanyDetails(
        id=orgnr,
        name=name.strip(),
        country="SE",
        legal_form=legal_form,
        status=status,
        incorporation_date=incorporation,
        registered_address=registered_address,
        capital_currency="SEK",
        nace_codes=nace_codes,
        identifiers=_identifiers(orgnr),
        raw={"bolagsverket": org},
        source_url=f"{_MACKAN_BASE}/get_data.php?orgnr={orgnr}",
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
    ).lower() == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}
