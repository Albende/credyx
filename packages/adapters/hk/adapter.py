"""Hong Kong adapter — Companies Registry (ICRIS) + HKEX.

Free public sources only, per the project's no-paid-API rule.

- **Registry** — Hong Kong Companies Registry "Cyber Search Centre"
  (https://www.icris.cr.gov.hk/csci/). The free tier exposes name search +
  CR number + status. Full company extracts and document downloads are
  HK$8/doc and not used here. ICRIS itself is a JSF/SPA that requires CSRF
  tokens and browser-rendered JavaScript — not scrapeable with plain httpx.
  We therefore route name search + CR-number lookup through the free
  OpenCorporates HK mirror (`jurisdiction_code=hk`) when an
  `OPENCORPORATES_API_KEY` is configured. Without a key the public ICRIS
  page is still surfaced as the `source_url`, but programmatic search /
  lookup raises `AdapterNotImplementedError` rather than fabricating data.

- **Financials** — Listed issuers file annual reports with HKEX
  (https://www.hkexnews.hk). The HKEX title-search backend is also a JSF
  page; we therefore expose the canonical listed-issuer Title Search URL
  per HKEX stock code when one is provided in `company_id` as
  `CR/HKEX:nnnn` (or just `HKEX:nnnn`). Plain CR-number callers with no
  HKEX code attached get `[]` — unlisted HK companies have no free
  financial source and we never invent one.

Identifiers
- `COMPANY_NUMBER` — 7-digit CR (Companies Registry) number, zero-padded.
- `OTHER` — 8-digit BR (Business Registration) number. Not the primary
  identifier (CR and BR diverge after company reorganizations); we accept
  it for normalization only.
"""
from __future__ import annotations

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
from packages.adapters._global.opencorporates import OpenCorporatesClient
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

_CR_RE = re.compile(r"^\d{1,7}$")
_BR_RE = re.compile(r"^\d{8}$")
_HKEX_RE = re.compile(r"^\d{1,5}$")

# CR codes can be packed alongside an HKEX stock code via the conventions
# "CR:1234567", "1234567/HKEX:0700", or "0700@hk" — these are accepted by
# fetch_financials so callers can pre-resolve the listing without us doing
# a second registry round-trip.
_PACKED_RE = re.compile(
    r"^(?:CR[:/])?(?P<cr>\d{1,7})?"
    r"(?:[/@]HKEX[:/]?(?P<hkex>\d{1,5}))?$",
    re.IGNORECASE,
)


def _normalize_cr_number(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.upper().startswith("CR"):
        cleaned = cleaned[2:].lstrip(":/")
    if not _CR_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"HK CR number must be up to 7 digits: {value}"
        )
    return cleaned.zfill(7)


def _normalize_br_number(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _BR_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"HK BR number must be 8 digits: {value}"
        )
    return cleaned


def _split_packed_id(value: str) -> tuple[str | None, str | None]:
    """Return (cr_number, hkex_code) parsed from a caller-supplied id."""
    raw = value.strip().replace(" ", "")
    m = _PACKED_RE.match(raw)
    if not m:
        return None, None
    cr = m.group("cr")
    hkex = m.group("hkex")
    cr_n = cr.zfill(7) if cr else None
    hkex_n = hkex.zfill(4) if hkex else None
    return cr_n, hkex_n


class HKAdapter(CountryAdapter):
    country_code = "HK"
    country_name = "Hong Kong"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.OTHER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    ICRIS_BASE = "https://www.icris.cr.gov.hk/csci/"
    HKEX_BASE = "https://www1.hkexnews.hk"
    HKEX_TITLE_SEARCH = (
        "https://www1.hkexnews.hk/search/titlesearch.xhtml"
        "?lang=EN&category=0&market=SEHK&stockId={hkex}"
        "&from={dfrom}&to={dto}"
    )

    def __init__(self, opencorporates_api_key: str | None = None) -> None:
        # OpenCorporates is optional; when its key is absent we degrade
        # gracefully rather than fabricating registry data.
        self.oc_key = opencorporates_api_key or os.getenv(
            "OPENCORPORATES_API_KEY"
        )
        self._oc = OpenCorporatesClient(api_key=self.oc_key) if self.oc_key else None

    async def health_check(self) -> AdapterHealth:
        notes: str | None
        capabilities = {
            "search": bool(self._oc),
            "lookup": bool(self._oc),
            "financials": True,
        }
        try:
            async with build_http_client(base_url=self.ICRIS_BASE, timeout=15.0) as client:
                resp = await get_with_retry(client, "/")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        if not self._oc:
            status = AdapterStatus.DEGRADED
            notes = (
                "ICRIS reachable. Set OPENCORPORATES_API_KEY to enable HK "
                "registry search/lookup (free tier, 500 req/month). "
                "Financials best-effort: HKEX index URL per listed issuer."
            )
        else:
            status = AdapterStatus.OK
            notes = (
                "Registry via OpenCorporates HK mirror. Financials "
                "best-effort: HKEX Title Search URL per listed issuer."
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities=capabilities,
            requires_api_key=False,
            api_key_present=bool(self._oc),
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not self._oc:
            raise AdapterNotImplementedError(
                "HK ICRIS Cyber Search Centre is a CSRF/SPA front-end that "
                "blocks programmatic clients, and the free CR open-data "
                "feed only ships full extracts behind a HK$8 paywall. Set "
                "OPENCORPORATES_API_KEY to enable HK name search via the "
                "free OpenCorporates HK mirror."
            )
        rows = await self._oc.search_companies(
            name, jurisdiction="hk", per_page=limit
        )
        matches: list[CompanyMatch] = []
        for row in rows[:limit]:
            cn = row.get("company_number")
            if not cn:
                continue
            try:
                cr = _normalize_cr_number(str(cn))
            except InvalidIdentifierError:
                continue
            matches.append(
                CompanyMatch(
                    id=cr,
                    name=(row.get("name") or "").strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=cr,
                            label="CR Number",
                        )
                    ],
                    address=_address_from_oc(row),
                    status=_status_from_oc(row),
                    source_url=row.get("opencorporates_url"),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            cr = _normalize_cr_number(value)
        elif id_type == IdentifierType.OTHER:
            # BR cannot be looked up on the free mirror (it isn't the
            # OpenCorporates primary key for HK); we don't fabricate a
            # CR <-> BR mapping.
            _normalize_br_number(value)
            raise AdapterNotImplementedError(
                "HK BR (Business Registration) lookup needs the paid IRD "
                "BR Number Enquiry. Pass the 7-digit CR number instead."
            )
        else:
            raise InvalidIdentifierError(
                f"HK supports COMPANY_NUMBER (CR) and OTHER (BR), got {id_type}"
            )

        if not self._oc:
            raise AdapterNotImplementedError(
                "HK CR lookup requires OPENCORPORATES_API_KEY (free tier) "
                "because ICRIS itself blocks programmatic clients."
            )
        company = await self._oc.get_company("hk", cr)
        if company is None:
            return None
        return _details_from_oc(company, cr)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cr, hkex = _split_packed_id(company_id)
        if cr is None and hkex is None:
            try:
                cr = _normalize_cr_number(company_id)
            except InvalidIdentifierError:
                cr = None
        if hkex is None and self._oc and cr is not None:
            hkex = await self._resolve_hkex_code(cr)
        if hkex is None:
            # Unlisted HK companies have no free financial source. Per
            # spec we return [] rather than inventing filings.
            return []

        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        for year in range(current_year - years, current_year + 1):
            url = self.HKEX_TITLE_SEARCH.format(
                hkex=hkex,
                dfrom=f"{year}0101",
                dto=f"{year}1231",
            )
            filings.append(
                FinancialFiling(
                    company_id=cr or f"HKEX:{hkex}",
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="HKD",
                    document_url=url,
                    document_format="html",
                    source_url=self.HKEX_BASE,
                )
            )
        return filings

    async def _resolve_hkex_code(self, cr: str) -> str | None:
        if not self._oc:
            return None
        company = await self._oc.get_company("hk", cr)
        if not company:
            return None
        # OpenCorporates HK rows occasionally carry the listing ticker in
        # the identifiers array (free tier). Treat anything else as
        # "unknown" — never guess.
        for ident in company.get("identifiers", []) or []:
            scheme = (ident.get("identifier_system_code") or "").lower()
            if "hkex" in scheme or "stock_exchange_of_hong_kong" in scheme:
                raw = str(ident.get("uid") or "").strip()
                if _HKEX_RE.match(raw):
                    return raw.zfill(4)
        return None


def _address_from_oc(row: dict[str, Any]) -> str | None:
    addr = row.get("registered_address_in_full") or row.get("registered_address")
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            addr.get("street_address"),
            addr.get("locality"),
            addr.get("region"),
            addr.get("postal_code"),
            addr.get("country"),
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    return None


def _status_from_oc(row: dict[str, Any]) -> str | None:
    s = row.get("current_status") or row.get("company_status")
    if not s:
        return None
    sl = str(s).lower()
    if any(tok in sl for tok in ("dissolved", "struck", "deregistered")):
        return "dissolved"
    if "active" in sl or "live" in sl:
        return "active"
    return str(s)


def _details_from_oc(company: dict[str, Any], cr: str) -> CompanyDetails:
    inc = company.get("incorporation_date")
    diss = company.get("dissolution_date")
    try:
        inc_d = date.fromisoformat(inc) if inc else None
    except (ValueError, TypeError):
        inc_d = None
    try:
        diss_d = date.fromisoformat(diss) if diss else None
    except (ValueError, TypeError):
        diss_d = None

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER,
            value=cr,
            label="CR Number",
        )
    ]
    for ident in company.get("identifiers", []) or []:
        scheme = (ident.get("identifier_system_code") or "").lower()
        uid = str(ident.get("uid") or "").strip()
        if not uid:
            continue
        if "br_number" in scheme or "business_registration" in scheme:
            try:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.OTHER,
                        value=_normalize_br_number(uid),
                        label="BR Number",
                    )
                )
            except InvalidIdentifierError:
                pass

    return CompanyDetails(
        id=cr,
        name=(company.get("name") or "").strip(),
        country="HK",
        legal_form=company.get("company_type"),
        status=_status_from_oc(company),
        incorporation_date=inc_d,
        dissolution_date=diss_d,
        registered_address=_address_from_oc(company),
        capital_currency="HKD",
        identifiers=identifiers,
        raw=company,
        source_url=(
            company.get("opencorporates_url")
            or f"https://www.icris.cr.gov.hk/csci/"
        ),
    )
