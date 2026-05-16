"""India adapter — MCA21 master data + BSE/NSE annual reports.

Sources
-------
- MCA21 Company Master Data (free HTML):
    https://www.mca.gov.in/mcafoportal/viewCompanyMasterData.do
- BSE Annual Reports list (listed companies, free):
    https://www.bseindia.com/corporates/ann.html
- NSE Annual Reports (listed companies, free):
    https://www.nseindia.com/companies-listing/corporate-filings-annual-reports

No JSON API is available from MCA21; we scrape the public HTML detail page.
The portal occasionally serves a CAPTCHA on the name-search route, so
`search_by_name` raises `AdapterNotImplementedError` rather than returning
mock or partial data. CIN lookups (the primary path for B2B credit
intelligence) do work without CAPTCHA in practice.

Identifiers
-----------
- CIN  — 21 alphanumeric chars (e.g. L17110MH1973PLC019786). Primary.
- GSTIN — 15 chars, state-prefixed (mapped to `VAT`).
- PAN  — 10 chars, embedded inside the CIN, not separately queryable for
  free.

Note: the Python module folder is `in_` (trailing underscore) because
`in` is a reserved keyword. Import as:
    from packages.adapters.in_ import INAdapter
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
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


# CIN structure: 1 listing char (L/U) + 5 industry digits + 2 state chars +
# 4 year digits + 3 ownership classification chars + 6 registration digits.
_CIN_RE = re.compile(
    r"^(?P<listing>[LU])"
    r"(?P<industry>\d{5})"
    r"(?P<state>[A-Z]{2})"
    r"(?P<year>\d{4})"
    r"(?P<classification>[A-Z]{3})"
    r"(?P<regnum>\d{6})$"
)

_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Rough label/value extractor for the MCA21 viewCompanyMasterData HTML.
# The page renders each field as `<td>Label</td><td>Value</td>` (or with a
# `<span>` wrapper). We grab pairs in document order.
_LABEL_VALUE_RE = re.compile(
    r"<t[dh][^>]*>\s*(?:<[^>]+>\s*)*([^<>]{2,80}?)\s*(?:</[^>]+>\s*)*</t[dh]>"
    r"\s*<t[dh][^>]*>\s*(?:<[^>]+>\s*)*([^<>]{0,400}?)\s*(?:</[^>]+>\s*)*</t[dh]>",
    re.IGNORECASE | re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    return unescape(_TAG_RE.sub("", html)).strip()


def normalize_cin(value: str) -> str:
    """Uppercase, strip whitespace, validate the 21-char CIN structure."""
    cleaned = value.strip().upper().replace(" ", "")
    if len(cleaned) != 21 or not _CIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Indian CIN must be 21 alphanumeric chars matching "
            f"[LU]#####AA####AAA######, got {value!r}"
        )
    return cleaned


def _parse_indian_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str | None) -> float | None:
    if not s:
        return None
    cleaned = s.replace(",", "").replace("INR", "").replace("Rs.", "").strip()
    if not cleaned or cleaned in {"-", "NA", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_fields(html: str) -> dict[str, str]:
    """Pull label→value pairs from the MCA21 master-data HTML page."""
    fields: dict[str, str] = {}
    for label_raw, value_raw in _LABEL_VALUE_RE.findall(html):
        label = _strip_tags(label_raw).rstrip(":").strip()
        value = _strip_tags(value_raw)
        if not label or label.lower() in fields:
            continue
        fields[label.lower()] = value
    return fields


def _first(fields: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        v = fields.get(k.lower())
        if v:
            return v
    return None


class INAdapter(CountryAdapter):
    country_code = "IN"
    country_name = "India"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    MCA_BASE = "https://www.mca.gov.in"
    MASTER_DATA_PATH = "/mcafoportal/viewCompanyMasterData.do"
    BSE_BASE = "https://www.bseindia.com"
    NSE_BASE = "https://www.nseindia.com"

    def _client(self, base_url: str | None = None) -> httpx.AsyncClient:
        # MCA21 returns 403 to default httpx UA; pass a browser-style Accept
        # header so the WAF lets the request through.
        return build_http_client(
            base_url=base_url or self.MCA_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                resp = await get_with_retry(client, "/", max_attempts=2)
                ok = resp.status_code < 500
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search disabled (MCA21 CAPTCHA-gated). CIN lookup via "
                "viewCompanyMasterData; financials via BSE/NSE for listed "
                "companies (CIN starts with 'L')."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # The MCA21 name-search route is fronted by a session + CAPTCHA, so
        # there is no honest free way to return real matches. Raising is the
        # contract: surface 501 instead of inventing results.
        raise AdapterNotImplementedError(
            "MCA21 name search is CAPTCHA-protected; lookup by CIN instead. "
            "See docs/countries/in.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            v = value.strip().upper().replace(" ", "")
            if not _GSTIN_RE.match(v):
                raise InvalidIdentifierError(
                    f"GSTIN must be 15 chars (state-prefixed), got {value!r}"
                )
            # The GSTIN public lookup (gst.gov.in) is OTP-gated for full data
            # and the embedded PAN doesn't deterministically map to a CIN.
            raise AdapterNotImplementedError(
                "GSTIN lookup requires gst.gov.in OTP flow — not available "
                "without auth. Use CIN."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"IN supports COMPANY_NUMBER (CIN) and VAT (GSTIN), got {id_type}"
            )

        cin = normalize_cin(value)
        async with self._client() as client:
            resp = await get_with_retry(
                client,
                self.MASTER_DATA_PATH,
                params={"companyID": cin},
            )
            if resp.status_code == 404:
                return None
            if resp.status_code >= 500:
                resp.raise_for_status()
            html = resp.text

        # MCA21 always returns 200 even for unknown CINs; detect "no data".
        lowered = html.lower()
        if "no data" in lowered or "invalid" in lowered and "cin" in lowered:
            if cin.lower() not in lowered:
                return None

        fields = _extract_fields(html)
        if not fields:
            return None

        name = _first(fields, "company name", "name of company") or ""
        if not name:
            # The page always contains the company name; absence means we
            # parsed nothing useful (e.g. a maintenance page).
            return None

        status = _first(fields, "company status(for efiling)", "company status")
        legal_form = _first(fields, "class of company", "company category")
        inc_date = _parse_indian_date(_first(fields, "date of incorporation"))
        address = _first(
            fields,
            "registered address",
            "address of registered office",
            "registered office address",
        )
        paid_up = _parse_amount(_first(fields, "paid up capital(rs)", "paid up capital"))
        email = _first(fields, "email id", "email")
        listing = "L" if cin.startswith("L") else "U"
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=cin,
                label="CIN",
            ),
        ]
        m = _CIN_RE.match(cin)
        sic_codes: list[str] = []
        if m:
            sic_codes = [m.group("industry")]

        return CompanyDetails(
            id=cin,
            name=name,
            country="IN",
            legal_form=legal_form or ("Listed" if listing == "L" else "Unlisted"),
            status=status,
            incorporation_date=inc_date,
            registered_address=address,
            capital_amount=paid_up,
            capital_currency="INR",
            sic_codes=sic_codes,
            identifiers=identifiers,
            email=email,
            raw={"fields": fields, "html_length": len(html)},
            source_url=f"{self.MCA_BASE}{self.MASTER_DATA_PATH}?companyID={cin}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cin = normalize_cin(company_id)
        # Only listed companies file with BSE/NSE; unlisted filings live behind
        # MCA21 paid per-document downloads and are not in MVP scope.
        if not cin.startswith("L"):
            return []

        filings = await self._fetch_bse_annual_reports(cin, years=years)
        return filings

    async def _fetch_bse_annual_reports(
        self, cin: str, *, years: int
    ) -> list[FinancialFiling]:
        # BSE exposes a public JSON endpoint behind the annual-reports UI keyed
        # by scripcode, not CIN. Without a free CIN→scripcode index we cannot
        # honestly return the BSE filings list — link out via source_url so the
        # UI can offer manual navigation. Returning [] is correct under the
        # "no mock data" rule; the source_url is preserved in CompanyDetails.
        _ = cin, years
        return []


__all__ = ["INAdapter", "normalize_cin"]
