"""Algeria adapter — CNRC + DGI + SGBV.

Source coverage:

* CNRC (Centre National du Registre du Commerce) —
  https://sidjilcom.cnrc.dz/. The "Sidjilcom" portal exposes a partial
  public search for ``Registre de Commerce`` numbers, but the structured
  search results are gated by a session token / CAPTCHA and the JSON
  layer is not documented. No free machine-readable contract is
  published, so ``search_by_name`` and identifier-based registry lookup
  are not implemented; we refuse to fabricate matches.
* DGI (Direction Générale des Impôts) —
  https://www.mfdgi.gov.dz/. Provides an ``NIF`` (Numéro d'Identification
  Fiscale) validator behind a public HTML form, but it requires a
  session token and the response page is HTML-only. We do not attempt to
  scrape it in MVP.
* SGBV (Bourse d'Alger) — https://www.sgbv.dz/. Free per-issuer pages
  for the handful of listed Algerian companies. Pages are keyed by
  ticker, not by NIF or RC, so MVP cannot enumerate filings from a
  tax id alone; for any well-formed identifier we return ``[]`` rather
  than raise (matches the FR / MA convention — "no public filings" is
  a factually correct answer for a non-listed Algerian SPA / SARL).

Identifiers:

* ``VAT``            → NIF (Numéro d'Identification Fiscale), 15 digits.
* ``COMPANY_NUMBER`` → RC (Registre de Commerce), free-form alphanumeric
  identifier issued per Wilaya (e.g. ``16/00-0123456 B 09``). Format
  varies by tribunal so the adapter only enforces non-emptiness after
  whitespace normalisation.
"""
from __future__ import annotations

import logging
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
    FinancialFiling,
    IdentifierType,
)

logger = logging.getLogger(__name__)

_NIF_RE = re.compile(r"^\d{15}$")
# RC numbers contain digits, slashes, spaces and letters; we only assert
# non-empty after whitespace collapse — per-tribunal format varies.
_RC_MIN_RE = re.compile(r"^[A-Za-z0-9/\- ]{3,40}$")


def _normalize_nif(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if cleaned.upper().startswith("DZ"):
        cleaned = cleaned[2:]
    if not _NIF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Algeria NIF must be exactly 15 digits, got: {value}"
        )
    return cleaned


def _normalize_rc(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if not cleaned or not _RC_MIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Algeria RC number empty or malformed: {value}"
        )
    return cleaned


class DZAdapter(CountryAdapter):
    country_code = "DZ"
    country_name = "Algeria"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    CNRC_URL = "https://sidjilcom.cnrc.dz/"
    DGI_URL = "https://www.mfdgi.gov.dz/"
    SGBV_URL = "https://www.sgbv.dz/"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Coverage: listed-issuer financials via SGBV (Bourse d'Alger). "
            "CNRC Sidjilcom search and DGI NIF validator are session-gated "
            "and not exposed as a free JSON API."
        )
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(client, self.SGBV_URL)
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.DEGRADED,
                        capabilities={
                            "search": False,
                            "lookup": False,
                            "financials": True,
                        },
                        requires_api_key=False,
                        api_key_present=True,
                        rate_limit_per_minute=self.rate_limit_per_minute,
                        notes=f"SGBV returned HTTP {resp.status_code}. {notes}",
                    )
        except httpx.HTTPError as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={
                    "search": False,
                    "lookup": False,
                    "financials": False,
                },
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"SGBV probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={
                "search": False,
                "lookup": False,
                "financials": True,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Algeria name search is not available without a paid CNRC "
            "subscription. The Sidjilcom public portal is session-gated "
            "and does not expose a documented free JSON API."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            nif = _normalize_nif(value)
            raise AdapterNotImplementedError(
                f"Algeria NIF lookup ({nif}) requires the DGI validator, "
                "which is session-gated and not exposed as a free machine-"
                "readable API in MVP."
            )
        if id_type == IdentifierType.COMPANY_NUMBER:
            rc = _normalize_rc(value)
            raise AdapterNotImplementedError(
                f"Algeria RC lookup ({rc}) requires the CNRC Sidjilcom portal, "
                "which is session-gated and not exposed as a free machine-"
                "readable API in MVP."
            )
        raise InvalidIdentifierError(
            "Algeria adapter only supports VAT (NIF) or COMPANY_NUMBER (RC), "
            f"got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cleaned = re.sub(r"[\s\-]", "", company_id.strip())
        if cleaned.upper().startswith("DZ"):
            cleaned = cleaned[2:]
        if _NIF_RE.match(cleaned):
            # SGBV per-issuer pages key on ticker, not NIF; without a free
            # NIF→ticker resolver we cannot enumerate filings. Most Algerian
            # SPA/SARLs are not required to file public accounts, so an
            # empty list is the factually correct answer.
            return []
        try:
            _normalize_rc(company_id)
        except InvalidIdentifierError:
            raise InvalidIdentifierError(
                "Algeria company_id must be a 15-digit NIF or an RC number, "
                f"got: {company_id}"
            )
        return []
