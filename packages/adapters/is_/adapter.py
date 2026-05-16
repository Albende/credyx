"""Iceland adapter — Skatturinn Fyrirtækjaskrá + Nasdaq Iceland.

Free public sources, no auth:

* **Skatturinn / RSK** (Iceland Revenue and Customs, https://www.skatturinn.is/)
  hosts the official company registry (Fyrirtækjaskrá) and VSK
  (virðisaukaskattsskrá / VAT) registry. The public search lives at
  ``/fyrirtaekjaskra/leit/`` and per-kennitala detail pages at
  ``/fyrirtaekjaskra/leit/uppfletting/?kt={kennitala}``. Skatturinn does
  not publish a documented JSON API — the public pages are HTML — so the
  adapter surfaces ``AdapterNotImplementedError`` for name search and
  per-kennitala detail rather than ever fabricating fields. Existence and
  reachability of the per-kennitala page is still probed live for the
  listed test companies covered by integration tests.
* **Nasdaq Iceland** (https://www.nasdaqomxnordic.com/) publishes free
  annual reports for listed issuers. ``fetch_financials`` returns
  per-year landing URLs for the requested window only when the issuer's
  Nasdaq Nordic profile page actually answers 200. Unlisted firms get
  ``[]`` — never a fake filing.

Identifier: **kennitala**. 10 digits, conventionally rendered ``DDMMYY-NNNN``.
For legal persons (companies / public institutions) the seventh digit is
adjusted by +4 so that ``DD`` lies in 41–71; the last two digits are a
mod-11 checksum followed by a century code (``9`` = 1900s, ``0`` = 2000s).
We normalize by stripping the optional ``IS`` prefix, spaces, and dashes,
then require exactly 10 digits — full mod-11 verification is out of scope
for the MVP but the shape check is strict.
"""
from __future__ import annotations

import re
from datetime import date, datetime

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
)


_KENNITALA_RE = re.compile(r"^\d{10}$")


def _normalize_kennitala(value: str) -> str:
    """Strip dashes, spaces, and an optional ``IS`` prefix; require 10 digits."""
    if value is None:
        raise InvalidIdentifierError("Iceland kennitala cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("IS"):
        cleaned = cleaned[2:]
    if not _KENNITALA_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Iceland kennitala must be exactly 10 digits, got: {value}"
        )
    return cleaned


def _format_kennitala(kt: str) -> str:
    """Return the canonical ``DDMMYY-NNNN`` display form."""
    return f"{kt[0:6]}-{kt[6:10]}"


class ISAdapter(CountryAdapter):
    country_code = "IS"
    country_name = "Iceland"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    SKATTURINN_BASE = "https://www.skatturinn.is"
    NASDAQ_BASE = "https://www.nasdaqomxnordic.com"

    def _skatturinn_headers(self) -> dict[str, str]:
        # Skatturinn responds normally only when a browser-style Accept
        # stack is presented; bare httpx defaults sometimes get a 406.
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "is;q=0.9, en;q=0.8",
            "Referer": f"{self.SKATTURINN_BASE}/fyrirtaekjaskra/leit/",
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.SKATTURINN_BASE,
                headers=self._skatturinn_headers(),
                timeout=15.0,
            ) as client:
                resp = await get_with_retry(client, "/fyrirtaekjaskra/leit/")
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"skatturinn.is HTTP {resp.status_code}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Skatturinn fyrirtækjaskrá reachable but its public search "
                "has no documented JSON API — search and lookup raise 501. "
                "Financials best-effort via Nasdaq Iceland for listed "
                "issuers only."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # Skatturinn's public name search is HTML-only with no documented
        # JSON endpoint we are entitled to consume. Rather than scrape
        # opportunistically and risk fabrication, surface 501.
        raise AdapterNotImplementedError(
            "Skatturinn fyrirtækjaskrá has no free documented JSON search API. "
            "See docs/countries/is.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Iceland supports VAT or COMPANY_NUMBER (kennitala), got {id_type}"
            )
        kt = _normalize_kennitala(value)
        raise AdapterNotImplementedError(
            "Skatturinn does not expose a free per-kennitala JSON lookup endpoint; "
            f"kennitala {_format_kennitala(kt)} cannot be resolved without HTML "
            "scraping. See docs/countries/is.md."
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # ``company_id`` is conventionally the raw kennitala. We accept an
        # opt-in ``NASDAQ:{ticker}`` prefix so callers can route a listed
        # issuer to its Nasdaq Iceland profile without us guessing the
        # kennitala-to-ticker mapping.
        cleaned = str(company_id or "").strip()
        symbol: str | None = None
        if cleaned.upper().startswith("NASDAQ:"):
            candidate = cleaned.split(":", 1)[1].strip().upper()
            if re.match(r"^[A-Z0-9]{2,12}$", candidate):
                symbol = candidate
        else:
            digits = re.sub(r"[\s\-.]", "", cleaned)
            if digits.upper().startswith("IS"):
                digits = digits[2:]
            if not _KENNITALA_RE.match(digits):
                raise InvalidIdentifierError(
                    "Iceland company_id must be a 10-digit kennitala or an explicit "
                    f"'NASDAQ:{{ticker}}' hint; got: {company_id}"
                )

        if not symbol:
            return []

        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        landing = (
            f"{self.NASDAQ_BASE}/shares/microsite"
            f"?Instrument={symbol}"
        )
        async with build_http_client(timeout=15.0) as client:
            try:
                probe = await client.get(landing)
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if probe.status_code != 200:
                return []
            for year in range(current_year - years, current_year):
                filings.append(
                    FinancialFiling(
                        company_id=cleaned,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="ISK",
                        document_url=(
                            f"{self.NASDAQ_BASE}/news/companynews"
                            f"?Instrument={symbol}&year={year}"
                        ),
                        document_format="html",
                        source_url=landing,
                    )
                )
        return filings
