"""India adapter — GLEIF LEI records + BSE annual reports.

Sources
-------
- GLEIF LEI records (free, no key): https://api.gleif.org/api/v1/lei-records
    Indian entities carry their MCA CIN in ``entity.registeredAs``, so the
    Global LEI index doubles as a free, key-less CIN lookup and name search
    for any Indian company that holds an LEI (all listed companies plus the
    large body of firms that trade or borrow internationally).
- BSE annual reports (free, no key):
    https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}
    Returns the filed annual-report PDFs per BSE scrip code.

Why not MCA21
-------------
The MCA V3 migration retired the old ``mcafoportal/viewCompanyMasterData.do``
master-data route (it now 302s to an error page); the V3 master-data screen
sits behind a login. GLEIF gives the same registry-grade identity data for
free without a session or CAPTCHA.

Identifiers
-----------
- CIN  — 21 alphanumeric chars (e.g. L17110MH1973PLC019786). Primary.
- GSTIN — 15 chars, state-prefixed (mapped to ``VAT``). The full gst.gov.in
  lookup is OTP-gated, so GSTIN is not resolvable for free.

Note: the Python module folder is ``in_`` (trailing underscore) because ``in``
is a reserved keyword. Import as:
    from packages.adapters.in_ import INAdapter
"""
from __future__ import annotations

import re

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

# BSE PeerSmartSearch returns an HTML fragment; each hit is an ng-click of the
# form liclick('<scripcode>','<company name>').
_BSE_HIT_RE = re.compile(r"liclick\('(\d+)','([^']+)'\)")

# Legal-form suffixes and noise words dropped when matching a GLEIF legal name
# against BSE's abbreviated scrip names ("... LIMITED" vs "... LTD").
_NAME_NOISE = {
    "LIMITED", "LTD", "PRIVATE", "PVT", "CORPORATION", "CORP",
    "COMPANY", "CO", "THE", "AND", "INDIA",
}


def normalize_cin(value: str) -> str:
    """Uppercase, strip whitespace, validate the 21-char CIN structure."""
    cleaned = value.strip().upper().replace(" ", "")
    if len(cleaned) != 21 or not _CIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Indian CIN must be 21 alphanumeric chars matching "
            f"[LU]#####AA####AAA######, got {value!r}"
        )
    return cleaned


def _normalize_name(name: str) -> str:
    tokens = re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split()
    kept = [t for t in tokens if t not in _NAME_NOISE]
    return " ".join(kept or tokens)


def _format_address(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts: list[str] = list(addr.get("addressLines") or [])
    for key in ("city", "region", "postalCode", "country"):
        val = addr.get(key)
        if val:
            parts.append(str(val))
    joined = ", ".join(p.strip() for p in parts if p and p.strip())
    return joined or None


class INAdapter(CountryAdapter):
    country_code = "IN"
    country_name = "India"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    GLEIF_BASE = "https://api.gleif.org"
    GLEIF_PATH = "/api/v1/lei-records"
    BSE_BASE = "https://api.bseindia.com"
    BSE_SEARCH_PATH = "/BseIndiaAPI/api/PeerSmartSearch/w"
    BSE_ANNUAL_PATH = "/BseIndiaAPI/api/AnnualReport_New/w"
    BSE_WEB = "https://www.bseindia.com"

    def _gleif_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
        )

    def _bse_client(self) -> httpx.AsyncClient:
        # api.bseindia.com rejects the default crawler UA; it wants a
        # browser-style UA plus a bseindia.com Referer.
        return build_http_client(
            base_url=self.BSE_BASE,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{self.BSE_WEB}/",
                "Origin": self.BSE_WEB,
            },
        )

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._gleif_client() as client:
                resp = await get_with_retry(
                    client, self.GLEIF_PATH, params={"page[size]": 1}, max_attempts=2
                )
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
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + CIN lookup via GLEIF (entity.registeredAs holds the "
                "MCA CIN). Financials via BSE annual reports for listed "
                "companies (CIN prefix 'L'). Covers any company holding an LEI."
            ),
        )

    async def _gleif_records(self, params: dict[str, str]) -> list[dict]:
        async with self._gleif_client() as client:
            resp = await get_with_retry(client, self.GLEIF_PATH, params=params)
            if resp.status_code >= 500:
                resp.raise_for_status()
            if resp.status_code == 404:
                return []
            data = resp.json()
        return data.get("data") or []

    def _record_to_match(self, record: dict) -> CompanyMatch | None:
        attrs = record.get("attributes", {})
        entity = attrs.get("entity", {})
        name = (entity.get("legalName") or {}).get("name")
        if not name:
            return None
        lei = record.get("id")
        cin = entity.get("registeredAs")
        identifiers: list[RegistryIdentifier] = []
        if cin and _CIN_RE.match(cin.upper()):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER, value=cin.upper(), label="CIN"
                )
            )
        if lei:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
            )
        return CompanyMatch(
            id=(cin.upper() if cin else lei) or name,
            name=name,
            country="IN",
            identifiers=identifiers,
            address=_format_address(entity.get("legalAddress")),
            status=entity.get("status"),
            source_url=f"{self.GLEIF_BASE}{self.GLEIF_PATH}/{lei}" if lei else None,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        records = await self._gleif_records(
            {
                "filter[entity.legalName]": query,
                "filter[entity.legalAddress.country]": "IN",
                "page[size]": str(min(max(limit, 1), 50)),
            }
        )
        matches: list[CompanyMatch] = []
        for record in records:
            match = self._record_to_match(record)
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            v = value.strip().upper().replace(" ", "")
            if not _GSTIN_RE.match(v):
                raise InvalidIdentifierError(
                    f"GSTIN must be 15 chars (state-prefixed), got {value!r}"
                )
            raise AdapterNotImplementedError(
                "GSTIN lookup requires the gst.gov.in OTP flow — not available "
                "without auth. Use CIN."
            )
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"IN supports COMPANY_NUMBER (CIN) and VAT (GSTIN), got {id_type}"
            )

        cin = normalize_cin(value)
        records = await self._gleif_records(
            {"filter[entity.registeredAs]": cin, "filter[entity.jurisdiction]": "IN"}
        )
        if not records:
            return None
        record = records[0]
        attrs = record.get("attributes", {})
        entity = attrs.get("entity", {})
        name = (entity.get("legalName") or {}).get("name")
        if not name:
            return None

        lei = record.get("id")
        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=cin, label="CIN"
            )
        ]
        if lei:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.LEI, value=lei, label="LEI")
            )

        m = _CIN_RE.match(cin)
        sic_codes = [m.group("industry")] if m else []
        listing = "Listed" if cin.startswith("L") else "Unlisted"
        legal_form = (entity.get("legalForm") or {}).get("id")

        return CompanyDetails(
            id=cin,
            name=name,
            country="IN",
            legal_form=legal_form or listing,
            status=entity.get("status"),
            registered_address=_format_address(entity.get("legalAddress")),
            capital_currency="INR",
            sic_codes=sic_codes,
            identifiers=identifiers,
            raw={
                "lei": lei,
                "entity": entity,
                "registration": attrs.get("registration", {}),
            },
            source_url=f"{self.GLEIF_BASE}{self.GLEIF_PATH}/{lei}" if lei else None,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cin = normalize_cin(company_id)
        # Only listed companies file annual reports with BSE/NSE; unlisted
        # filings sit behind MCA21 paid per-document downloads (out of MVP scope).
        if not cin.startswith("L"):
            return []

        details = await self.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, cin)
        if details is None:
            return []

        scripcode = await self._resolve_bse_scripcode(details.name)
        if scripcode is None:
            return []

        return await self._fetch_bse_annual_reports(cin, scripcode, years=years)

    async def _resolve_bse_scripcode(self, legal_name: str) -> str | None:
        target = _normalize_name(legal_name)
        search_term = target or legal_name
        async with self._bse_client() as client:
            resp = await get_with_retry(
                client,
                self.BSE_SEARCH_PATH,
                params={"Type": "SS", "text": search_term},
            )
            if resp.status_code >= 400:
                return None
            body = resp.text

        best_prefix: str | None = None
        for scripcode, hit_name in _BSE_HIT_RE.findall(body):
            normalized = _normalize_name(hit_name)
            if normalized == target:
                return scripcode
            if best_prefix is None and (
                normalized.startswith(target) or target.startswith(normalized)
            ):
                best_prefix = scripcode
        return best_prefix

    async def _fetch_bse_annual_reports(
        self, cin: str, scripcode: str, *, years: int
    ) -> list[FinancialFiling]:
        async with self._bse_client() as client:
            resp = await get_with_retry(
                client, self.BSE_ANNUAL_PATH, params={"scripcode": scripcode}
            )
            if resp.status_code >= 400:
                return []
            payload = resp.json()

        rows = payload.get("Table") or []
        source_url = (
            f"{self.BSE_WEB}/corporates/List_Scrips.html"
            f"?scripcode={scripcode}"
        )
        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for row in rows:
            year_raw = str(row.get("Year") or "").strip()
            pdf = (row.get("PDFDownload") or "").strip()
            if not year_raw.isdigit() or not pdf.startswith("http"):
                continue
            year = int(year_raw)
            if year in seen_years:
                continue
            seen_years.add(year)
            filings.append(
                FinancialFiling(
                    company_id=cin,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    currency="INR",
                    document_url=pdf,
                    document_format="pdf",
                    source_url=source_url,
                )
            )
            if len(filings) >= years:
                break
        return filings


__all__ = ["INAdapter", "normalize_cin"]
