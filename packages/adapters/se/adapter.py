"""Sweden adapter — VIES VAT + Nasdaq Stockholm for listed firms.

Sweden's authoritative business registry is **Bolagsverket
Näringslivsregistret**. The full-extract API (Näringslivsregistret API)
requires a paid subscription contract and is therefore out of scope for
the free MVP (project rule #2). Bolagsverket also publishes a small
open-data slice at https://bolagsverket.se/ofr/ but it does not expose
per-company lookup.

What is freely usable today:

- **VIES** (EU VAT Information Exchange) validates a Swedish VAT number
  (`SE` + 12 digits, where the first 10 digits are the Organisationsnummer
  and the last two are always `01`) and returns the registered name +
  address.
- **Nasdaq Stockholm** publishes annual report links on each listed
  issuer's company page. For test-universe listed companies (Volvo,
  Ericsson, H&M) we surface durable issuer URLs as financial filings.
- `allabolag.se` / `merinfo.se` are deliberately *not* used: their ToS
  explicitly forbids automated scraping, which conflicts with project
  rule #2 (no paid / ToS-grey scraping in MVP).

So `lookup_by_identifier` hits VIES, `fetch_financials` returns Nasdaq
Stockholm pointers for listed entities (empty otherwise), and
`search_by_name` raises — there is no free authoritative Swedish name
search.

Organisationsnummer format: 10 digits, typically printed `XXXXXX-XXXX`.
The 10th digit is a Luhn (mod-10) check digit over the first 9. Companies
all have a "group number" (the first digit) of 5; sole-proprietor
"enskild firma" numbers re-use the owner's personnummer.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client
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

# Volvo AB — stable, always-valid Organisationsnummer used as a VIES probe.
_VIES_HEALTH_PROBE = "556012579001"

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
    right, doubling every other digit starting at position 1 (the
    leftmost). If a doubled value exceeds 9, sum its digits. The check
    digit must make the total a multiple of 10.
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
    century-prefixed form, and a `SE` prefix. Validates Luhn.
    """
    cleaned = value.strip().upper().replace(" ", "").replace("-", "").replace(".", "")
    if cleaned.startswith("SE"):
        cleaned = cleaned[2:]
    # SE VAT is 12 digits: 10-digit Org Nr + "01". Drop the suffix when
    # the caller hands us a VAT-shaped string under the COMPANY_NUMBER
    # type.
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


# Known Swedish listed issuers on Nasdaq Stockholm. The canonical pivot
# for Nasdaq URLs is the ticker symbol, not the Org Nr, so we maintain a
# small explicit map for the test universe. Extending this to every
# listed Swedish issuer would require parsing the Nasdaq listed-companies
# index — a follow-up once the scraper pool lands.
_NASDAQ_TICKER_BY_ORGNR: dict[str, str] = {
    "5560125790": "VOLV-B",     # AB Volvo
    "5560160680": "ERIC-B",     # Telefonaktiebolaget LM Ericsson
    "5560427220": "HM-B",       # H&M Hennes & Mauritz AB
    "5590260892": "SPOT",       # Spotify Technology — listed on NYSE
}


def _nasdaq_company_url(orgnr: str) -> str | None:
    ticker = _NASDAQ_TICKER_BY_ORGNR.get(orgnr)
    if not ticker:
        return None
    return (
        f"https://www.nasdaq.com/market-activity/stocks/"
        f"{ticker.lower()}/financials"
    )


class SEAdapter(CountryAdapter):
    country_code = "SE"
    country_name = "Sweden"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    VIES_URL = _VIES_URL

    async def health_check(self) -> AdapterHealth:
        try:
            payload = await self._vies_check(_VIES_HEALTH_PROBE[:10])
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"VIES probe failed: {str(exc)[:160]}",
            )
        if not payload or not payload.get("valid"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="VIES reachable but Volvo VAT reported invalid.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via VIES; financials only for Nasdaq Stockholm-listed "
                "firms. Name search unavailable from any free authoritative "
                "source (Bolagsverket Näringslivsregistret is paid)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Sweden has no free authoritative name-search API. Bolagsverket "
            "Näringslivsregistret is paid; allabolag.se / merinfo.se forbid "
            "scraping in their ToS. Use OpenCorporates global search or look "
            "up directly by Organisationsnummer."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            vat = _normalize_se_vat(value)
            orgnr = vat[:10]
        elif id_type == IdentifierType.COMPANY_NUMBER:
            orgnr = _normalize_orgnr(value)
        else:
            raise InvalidIdentifierError(
                f"SE supports COMPANY_NUMBER (Org Nr) / VAT, got {id_type}"
            )

        vies = await self._vies_check(orgnr)
        if not vies or not vies.get("valid"):
            return None

        nasdaq_url = _nasdaq_company_url(orgnr)
        identifiers = [
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
        return CompanyDetails(
            id=orgnr,
            name=(vies.get("name") or "").strip() or orgnr,
            country="SE",
            legal_form=None,
            status="active",
            registered_address=(vies.get("address") or "").strip() or None,
            capital_currency="SEK",
            identifiers=identifiers,
            raw={"vies": vies, "nasdaq_listed": bool(nasdaq_url)},
            source_url=nasdaq_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        orgnr = _normalize_orgnr(company_id)
        nasdaq_url = _nasdaq_company_url(orgnr)
        if not nasdaq_url:
            return []
        # Nasdaq publishes annual reports on each issuer's financials page;
        # per-document URLs require parsing the page, which is a follow-up
        # once the scraper pool lands. Surface one entry per recent year
        # pointing at the durable financials page so the LLM / operator
        # can deep-link in.
        current_year = datetime.utcnow().year
        filings: list[FinancialFiling] = []
        for offset in range(1, years + 1):
            year = current_year - offset
            filings.append(
                FinancialFiling(
                    company_id=orgnr,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="SEK",
                    structured_data=None,
                    document_url=None,
                    document_format=None,
                    source_url=nasdaq_url,
                )
            )
        return filings

    async def _vies_check(self, orgnr: str) -> dict[str, Any] | None:
        # VIES checkVat takes the local-format VAT digits. For SE that is
        # the 10-digit Org Nr + "01" suffix.
        vat = f"{orgnr}01"
        envelope = _VIES_ENVELOPE.format(cc="SE", vat=vat)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "",
        }
        async with build_http_client(timeout=30.0, headers=headers) as client:
            resp = await client.post(self.VIES_URL, content=envelope)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        return _parse_vies_response(resp.text)


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
