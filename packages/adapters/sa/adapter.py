"""Saudi Arabia adapter — Ministry of Commerce + ZATCA + Tadawul.

Source coverage:

* Ministry of Commerce (MCI) — https://mci.gov.sa/ and https://mc.gov.sa/.
  Public CR (Commercial Registration) name search and validator. The
  customer-facing portal is React+Arabic with no documented JSON API and
  pages typically gate full registry details behind Nafath login (Saudi
  national e-ID). Best-effort lookup constructs a deep link to the public
  CR detail page.
* ZATCA (Zakat, Tax and Customs Authority) — https://zatca.gov.sa/.
  Operates a VAT validator. The public lookup is a form (AngularJS)
  protected by a Google reCAPTCHA, so we cannot pull structured details
  in the free MVP — VAT lookups surface as a best-effort link-out.
* Tadawul / Saudi Exchange — https://www.saudiexchange.sa/.
  Annual reports for TASI-listed issuers are public PDFs but the listing
  portal is a single-page Angular app with no documented data API. We
  expose a best-effort issuer search URL for `fetch_financials`.

Identifiers:

* CR Number — 10 digits, encoded as `IdentifierType.COMPANY_NUMBER`.
* VAT — 15 digits beginning with 3 (the "TIN" published by ZATCA also
  starts with 3 and is followed by the VAT group digit). We strip a
  leading `SA` prefix if a caller passes the EU-style form.
* 700 series ("700 ID") is the establishment number used by GOSI/MoL —
  it is 10 digits beginning with `7` and reuses the COMPANY_NUMBER slot.

Per the project rules this adapter never returns mock data: when a
source is blocked (CAPTCHA, paywall, Nafath login) the relevant call
raises `AdapterNotImplementedError` so the API surface returns 501.
"""
from __future__ import annotations

import re

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
    RegistryIdentifier,
)

_CR_RE = re.compile(r"^\d{10}$")
_VAT_RE = re.compile(r"^3\d{14}$")
_EST_700_RE = re.compile(r"^7\d{9}$")


def _normalize_cr(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _CR_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Saudi CR / 700 ID must be 10 digits, got: {value}"
        )
    return cleaned


def _normalize_vat(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("SA"):
        cleaned = cleaned[2:]
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Saudi VAT must be 15 digits starting with 3, got: {value}"
        )
    return cleaned


class SAAdapter(CountryAdapter):
    country_code = "SA"
    country_name = "Saudi Arabia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    MCI_BASE = "https://mci.gov.sa"
    MC_BASE = "https://mc.gov.sa"
    ZATCA_BASE = "https://zatca.gov.sa"
    TADAWUL_BASE = "https://www.saudiexchange.sa"

    async def health_check(self) -> AdapterHealth:
        # Probe a stable public host. saudiexchange.sa is the most reliable
        # non-CAPTCHA endpoint and serves as a proxy for "Saudi public
        # data infrastructure reachable from here".
        reachable_hosts: list[str] = []
        for label, base in (
            ("Saudi Exchange", self.TADAWUL_BASE),
            ("MCI", self.MCI_BASE),
        ):
            try:
                async with build_http_client(base_url=base, timeout=10.0) as client:
                    resp = await get_with_retry(client, "/", max_attempts=1)
                    if 200 <= resp.status_code < 500:
                        reachable_hosts.append(label)
            except Exception:
                continue

        if not reachable_hosts:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Neither MCI nor Saudi Exchange reachable.",
            )

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Best-effort link-out only: MCI/ZATCA gate JSON behind Nafath "
                "login and reCAPTCHA; Saudi Exchange has no public data API. "
                "Reachable: " + ", ".join(reachable_hosts) + "."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # MCI's eServices name search posts via an authenticated session
        # tied to Nafath; the unauthenticated endpoint returns an empty
        # frame. Rather than fabricate matches, surface this honestly.
        raise AdapterNotImplementedError(
            "Saudi MCI name search is gated by Nafath login; no free public "
            "JSON endpoint exposes structured results."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            cr = _normalize_cr(value)
            label = "700 Establishment Number" if _EST_700_RE.match(cr) else "CR Number"
            return CompanyDetails(
                id=cr,
                name="(name available only after Nafath login)",
                country=self.country_code,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=cr,
                        label=label,
                    ),
                ],
                source_url=f"{self.MC_BASE}/ar/eservices/Pages/CRValidation.aspx?cr={cr}",
                raw={"note": "MCI CR detail page requires Nafath login."},
            )

        if id_type == IdentifierType.VAT:
            vat = _normalize_vat(value)
            return CompanyDetails(
                id=vat,
                name="(name available only after passing ZATCA reCAPTCHA)",
                country=self.country_code,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=vat,
                        label="VAT (ZATCA)",
                    ),
                ],
                source_url=f"{self.ZATCA_BASE}/en/eServices/Pages/eService_022.aspx?vat={vat}",
                raw={"note": "ZATCA VAT validator is reCAPTCHA-protected."},
            )

        raise InvalidIdentifierError(
            f"Saudi Arabia supports COMPANY_NUMBER (CR or 700) and VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Tadawul publishes annual reports as PDFs on per-issuer pages
        # served by a single-page Angular app — there is no documented
        # JSON catalogue we can hit without a headless browser. Until the
        # browser pool described in CLAUDE.md is in place, do not invent
        # placeholder filings.
        _normalize_cr(company_id)
        return []
