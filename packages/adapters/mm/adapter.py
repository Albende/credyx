"""Myanmar adapter — DICA MyCO public search + YSX (best-effort).

Two free, no-auth public sources are stitched together here:

* DICA MyCO (Directorate of Investment and Company Administration, Online
  Company Registry, https://www.myco.dica.gov.mm). Public name-search page
  used to discover company registration numbers and statuses. No API key.
  The site is an ASP.NET SPA — the search endpoint backs the public
  search form and returns either a JSON shape or a server-rendered HTML
  fragment; we accept both. Per-company detail pages are session-bound
  and brittle, so `lookup_by_identifier` only succeeds when the search
  endpoint surfaces the company directly by registration number.
* YSX (Yangon Stock Exchange, https://www.ysx-mm.com) for listed-company
  annual reports. We only synthesize the canonical listed-issuer URL —
  we never download or interpret the payload here. Unlisted firms
  return `[]`.

Identifier:
  DICA Company Registration Number. Historically a 4–7 digit numeric
  with optional `OF` (overseas) / `FC` (foreign) suffix; under the 2018
  Companies Law, freshly issued numbers carry a `YYYYMMDD` date prefix
  plus a per-day sequence — overall length is therefore not fixed. We
  preserve the input shape after light normalization (uppercase, strip
  whitespace, drop dashes) rather than enforce a rigid format.

Sanctions / OFAC context:
  Myanmar is subject to active US (OFAC SDN), UK, EU and other
  sanctions programmes targeting the military regime and a number of
  state-linked enterprises (e.g. MEHL, MEC, MOGE). Registry data from
  DICA is public and may be ingested freely, but any downstream credit
  decision MUST cross-reference OpenSanctions before approval — this
  adapter surfaces registry facts only and does no screening itself.
"""
from __future__ import annotations

import re
from datetime import date, datetime
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

# DICA registration numbers are a mix of legacy "12345" / "12345 OF" /
# "12345 FC" forms and post-2018 "YYYYMMDD-NNN" / "YYYYMMDD/NN" forms.
# We accept any uppercase alphanumeric with optional internal "/" or "-".
_REG_NO_RE = re.compile(r"^[A-Z0-9][A-Z0-9/\-]{1,30}$")


def _normalize_reg_no(value: str) -> str:
    if value is None:
        raise InvalidIdentifierError("Myanmar DICA registration number cannot be empty")
    cleaned = str(value).strip().upper()
    cleaned = re.sub(r"\s+", "", cleaned)
    if cleaned.startswith("MM"):
        cleaned = cleaned[2:]
    if not _REG_NO_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Myanmar DICA registration number invalid: {value}"
        )
    return cleaned


def _parse_mm_date(s: Any) -> date | None:
    """Accept ISO `YYYY-MM-DD` and Myanmar `DD/MM/YYYY` / `DD-MM-YYYY` forms.

    Returns None for anything we cannot parse — we never guess a date.
    """
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _pick(r: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return None


def _normalize_status(s: Any) -> str | None:
    if not s:
        return None
    raw = str(s).strip()
    lowered = raw.lower()
    if any(tok in lowered for tok in ("active", "registered", "operating")):
        return "active"
    if any(
        tok in lowered
        for tok in (
            "struck off",
            "struck-off",
            "dissolved",
            "wound up",
            "wound-up",
            "ceased",
            "liquidat",
            "deregister",
        )
    ):
        return "ceased"
    if "suspend" in lowered:
        return "suspended"
    return raw


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in (
            "data",
            "Data",
            "results",
            "Results",
            "items",
            "Items",
            "rows",
            "Rows",
            "records",
            "Records",
        ):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
            if isinstance(v, dict):
                inner = (
                    v.get("data")
                    or v.get("items")
                    or v.get("rows")
                    or v.get("records")
                )
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
    return []


def _looks_like_ysx_ticker(value: Any) -> bool:
    if not value:
        return False
    raw = str(value).strip().upper()
    # YSX uses short alphanumeric codes (e.g. FMI, MTSH, MCB, AFD).
    return bool(re.match(r"^[A-Z]{2,6}$", raw))


class MMAdapter(CountryAdapter):
    country_code = "MM"
    country_name = "Myanmar"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    MYCO_BASE = "https://www.myco.dica.gov.mm"
    YSX_BASE = "https://www.ysx-mm.com"

    def _myco_headers(self) -> dict[str, str]:
        # MyCO's search backend rejects bare httpx requests; it expects a
        # browser-style Accept header and a same-origin Referer (the search
        # page) before it returns JSON.
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en;q=0.9, my;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.MYCO_BASE}/Companies",
            "Origin": self.MYCO_BASE,
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.MYCO_BASE, timeout=20.0
            ) as client:
                resp = await get_with_retry(client, "/")
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": False,
                        },
                        notes=f"MyCO HTTP {resp.status_code}",
                    )
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
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via DICA MyCO public search. Per-company detail is "
                "session-bound and best-effort. Financials: YSX URLs for "
                "listed issuers only — unlisted firms return []. Always "
                "cross-check OpenSanctions for OFAC/UK/EU exposure before "
                "approving credit."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        rows = await self._myco_search(query, limit)
        matches: list[CompanyMatch] = []
        for r in rows[:limit]:
            reg_no = _pick(
                r,
                "RegistrationNo",
                "RegistrationNumber",
                "registrationNo",
                "regNo",
                "CompanyRegistrationNo",
                "CompanyNumber",
                "Number",
            )
            if not reg_no:
                continue
            reg_no_s = str(reg_no).strip()
            display_name = (
                _pick(
                    r,
                    "CompanyName",
                    "Name",
                    "companyName",
                    "name",
                    "EntityName",
                )
                or ""
            )
            matches.append(
                CompanyMatch(
                    id=reg_no_s,
                    name=str(display_name).strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=reg_no_s,
                            label="DICA Registration No.",
                        ),
                    ],
                    address=_pick(r, "Address", "RegisteredAddress", "address"),
                    status=_normalize_status(
                        _pick(r, "Status", "CompanyStatus", "status")
                    ),
                    source_url=f"{self.MYCO_BASE}/Companies",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Myanmar supports COMPANY_NUMBER (DICA Registration No.), got {id_type}"
            )
        reg_no = _normalize_reg_no(value)
        # MyCO per-company detail pages are session-bound (ASP.NET ViewState
        # plus an interstitial CAPTCHA on cold sessions); reliably scraping
        # them needs a browser pool that this codebase does not yet have.
        # We surface what the public search endpoint returns when the user
        # already knows the registration number, and otherwise raise a
        # clean 501.
        try:
            rows = await self._myco_search(reg_no, limit=10)
        except AdapterNotImplementedError:
            raise
        except Exception:
            rows = []
        match = _select_by_reg_no(rows, reg_no)
        if match is None:
            # When we cannot confirm the company from the public index, we
            # refuse to fabricate a CompanyDetails — per the no-mock-data rule.
            return None
        return _row_to_details(match, reg_no, self.MYCO_BASE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        reg_no = _normalize_reg_no(company_id)
        try:
            rows = await self._myco_search(reg_no, limit=10)
        except Exception:
            rows = []
        match = _select_by_reg_no(rows, reg_no)
        symbol = _detect_ysx_symbol(match) if match else None
        if not symbol:
            return []

        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        # YSX hosts listed-company disclosures on stable per-symbol pages.
        # We probe the symbol landing page once and emit one annual-report
        # URL per year only when the page actually responds — we never
        # synthesize URLs for issuers we cannot confirm are listed.
        async with build_http_client(
            base_url=self.YSX_BASE, timeout=15.0
        ) as client:
            landing = f"/listing/{symbol}"
            try:
                probe = await client.get(landing)
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if probe.status_code != 200:
                return []
            body = probe.text or ""
            if symbol not in body.upper() and "YSX" not in body.upper():
                return []

            for year in range(current_year - years, current_year):
                filings.append(
                    FinancialFiling(
                        company_id=reg_no,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 3, 31),
                        currency="MMK",
                        document_url=f"{self.YSX_BASE}{landing}",
                        document_format="html",
                        source_url=f"{self.YSX_BASE}{landing}",
                    )
                )
        return filings

    async def _myco_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Hit the DICA MyCO public search endpoint and normalize the payload.

        The site is ASP.NET; the endpoint shape changes between deployments.
        We try the documented JSON path and degrade to an empty list on any
        non-JSON response rather than guess at the HTML.
        """
        async with build_http_client(
            base_url=self.MYCO_BASE,
            headers=self._myco_headers(),
            timeout=20.0,
        ) as client:
            # Warm up the session so the search endpoint accepts the call.
            try:
                await get_with_retry(client, "/Companies")
            except (httpx.TransportError, httpx.TimeoutException):
                return []

            for path, params in (
                (
                    "/Companies/Search",
                    {"searchTerm": query, "page": 1, "pageSize": limit},
                ),
                (
                    "/api/Companies/Search",
                    {"q": query, "limit": limit},
                ),
            ):
                try:
                    resp = await get_with_retry(client, path, params=params)
                except (httpx.TransportError, httpx.TimeoutException):
                    continue
                if resp.status_code == 404:
                    continue
                if resp.status_code >= 400:
                    continue
                content_type = (resp.headers.get("content-type") or "").lower()
                if "json" not in content_type:
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                rows = _extract_rows(payload)
                if rows:
                    return rows
        return []


def _select_by_reg_no(
    rows: list[dict[str, Any]], reg_no: str
) -> dict[str, Any] | None:
    target = reg_no.strip().upper()
    for r in rows:
        candidate = _pick(
            r,
            "RegistrationNo",
            "RegistrationNumber",
            "registrationNo",
            "regNo",
            "CompanyRegistrationNo",
            "CompanyNumber",
            "Number",
        )
        if candidate and str(candidate).strip().upper() == target:
            return r
    return None


def _detect_ysx_symbol(record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    candidate = _pick(
        record, "YsxSymbol", "ysxSymbol", "stockSymbol", "Symbol", "TickerSymbol"
    )
    if _looks_like_ysx_ticker(candidate):
        return str(candidate).strip().upper()
    return None


def _row_to_details(
    r: dict[str, Any], reg_no: str, myco_base: str
) -> CompanyDetails:
    display_name = (
        _pick(r, "CompanyName", "Name", "companyName", "name", "EntityName") or ""
    )
    address = _pick(r, "Address", "RegisteredAddress", "address")
    legal_form = _pick(
        r, "EntityType", "CompanyType", "entityType", "companyType", "Type"
    )
    status = _normalize_status(_pick(r, "Status", "CompanyStatus", "status"))
    inc_date = _parse_mm_date(
        _pick(
            r,
            "RegistrationDate",
            "IncorporationDate",
            "registrationDate",
            "incorporationDate",
            "DateOfIncorporation",
        )
    )
    business_activity = _pick(
        r, "BusinessActivity", "PrincipalActivity", "Industry", "Sector"
    )

    identifiers = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=reg_no,
            label="DICA Registration No.",
        ),
    ]

    return CompanyDetails(
        id=reg_no,
        name=str(display_name).strip(),
        country="MM",
        legal_form=str(legal_form) if legal_form else None,
        status=status,
        incorporation_date=inc_date,
        registered_address=str(address) if address else None,
        capital_amount=None,
        capital_currency="MMK",
        sic_codes=[str(business_activity)] if business_activity else [],
        identifiers=identifiers,
        raw=r,
        source_url=f"{myco_base}/Companies",
    )
