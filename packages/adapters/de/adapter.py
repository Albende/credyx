"""Germany adapter — currently NOT operational: no free live registry source.

Status (verified live 2026-07-20):
- OffeneRegister.de, the free JSON mirror of the Handelsregister this adapter
  was built on, has shut its API down. https://offeneregister.de is now a
  static GitHub Pages site that only offers the bulk SQLite dump for
  download (`/api/v1/*` returns a GitHub Pages 404 HTML page), and the
  Datasette instance at https://db.offeneregister.de/ answers 502 Bad
  Gateway. The underlying data snapshot was from 2019 anyway.
- handelsregister.de (official) is web-only, session-bound, and charges
  €1 per filing document — out of scope per the MVP "no paid APIs" rule.
- Bundesanzeiger financials scraping depended on resolving the company name
  through OffeneRegister, so it is disabled with the rest.

Per the "no mock data" rule every method raises
``AdapterNotImplementedError`` (the API surfaces it as 501) — after
validating the identifier format so malformed input still gets an
actionable ``InvalidIdentifierError``.

Free paths forward:
- GLEIF / OpenCorporates via ``packages/adapters/_global`` cover large
  German entities by LEI / mirrored registry data.
- Ingest the OffeneRegister bulk SQLite dump (several GB, 2019 snapshot)
  behind a local lookup service.
- A Playwright-based handelsregister.de search (free name search exists on
  the portal) once the browser-pool infrastructure lands.

Identifiers (validated even while lookups are disabled):
- HRB/HRA number, with or without prefix and registering court:
  ``42243``, ``HRB 42243``, ``HRB 42243 München``.
- COMPANY_NUMBER — historical OffeneRegister slug.
- VAT — USt-IdNr, ``DE`` + 9 digits.
"""
from __future__ import annotations

import re
from datetime import datetime

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
    FinancialFiling,
    IdentifierType,
)

_HRB_RE = re.compile(r"^(?:HR[AB]\s*)?(\d{1,6})(?:\s+\S.*)?$", re.IGNORECASE)
_VAT_RE = re.compile(r"^DE\d{9}$", re.IGNORECASE)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]+$")

_SOURCE_GONE = (
    "German registry lookups are unavailable: the free OffeneRegister.de "
    "mirror API shut down (checked 2026-07-20 — the site only offers a bulk "
    "SQLite dump; db.offeneregister.de answers 502), and handelsregister.de "
    "is web-only/session-bound with paid filings. No free live source "
    "remains. Alternatives: GLEIF/OpenCorporates via packages/adapters/"
    "_global, or ingest the OffeneRegister bulk dump. See docs/countries/de.md."
)


class DEAdapter(CountryAdapter):
    country_code = "DE"
    country_name = "Germany"
    identifier_types = [
        IdentifierType.HRB,
        IdentifierType.COMPANY_NUMBER,
        IdentifierType.VAT,
    ]
    primary_identifier = IdentifierType.HRB
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://offeneregister.de"

    async def health_check(self) -> AdapterHealth:
        # One light probe so we notice if the mirror ever comes back.
        api_alive = False
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(
                    client, "/api/v1/companies", params={"name": "siemens", "size": 1}
                )
                ctype = (resp.headers.get("content-type") or "").lower()
                api_alive = resp.status_code == 200 and "json" in ctype
        except Exception:
            api_alive = False
        if api_alive:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                last_checked_at=datetime.utcnow(),
                notes=(
                    "OffeneRegister API is answering JSON again — the DE "
                    "adapter was disabled while it was offline and needs "
                    "re-enabling."
                ),
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.NOT_IMPLEMENTED,
            capabilities={"search": False, "lookup": False, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=_SOURCE_GONE,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(_SOURCE_GONE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        cleaned = value.strip()
        if id_type == IdentifierType.HRB:
            if not _HRB_RE.match(cleaned):
                raise InvalidIdentifierError(
                    "German Handelsregister number must be the register "
                    "number with optional HRB/HRA prefix and court, e.g. "
                    f"'42243', 'HRB 42243', or 'HRB 42243 München' — got {value!r}"
                )
        elif id_type == IdentifierType.COMPANY_NUMBER:
            if not _SLUG_RE.match(cleaned.lower()):
                raise InvalidIdentifierError(
                    f"Not a valid OffeneRegister slug: {value!r}"
                )
        elif id_type == IdentifierType.VAT:
            if not _VAT_RE.match(cleaned.upper().replace(" ", "")):
                raise InvalidIdentifierError(
                    f"German VAT must be DE + 9 digits (e.g. DE129273398): {value!r}"
                )
        else:
            raise InvalidIdentifierError(
                f"DE supports HRB, COMPANY_NUMBER (slug), VAT — got {id_type}"
            )
        raise AdapterNotImplementedError(_SOURCE_GONE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # The Bundesanzeiger scrape resolved company names via OffeneRegister,
        # so it went down with the mirror.
        raise AdapterNotImplementedError(_SOURCE_GONE)
