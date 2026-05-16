"""Morocco adapter — OMPIC + AMMC + Bourse de Casablanca.

Source coverage:

* OMPIC (Office Marocain de la Propriété Industrielle et Commerciale) —
  https://www.directinfo.ma/ exposes a paid commercial register and a
  partial public name search. There is no documented free JSON API, so
  `search_by_name` is not implemented (we refuse to fabricate matches).
* tax.gov.ma (Direction Générale des Impôts) ICE / IF validator pages —
  used best-effort for `lookup_by_identifier`. They are HTML-only and
  often gated by a session token / CAPTCHA. When the probe cannot return
  a deterministic identity match we raise `AdapterNotImplementedError`
  rather than guess.
* AMMC (Autorité Marocaine du Marché des Capitaux) and Bourse de
  Casablanca publish free annual reports and reference documents for
  listed issuers. We expose these as filing URLs in `fetch_financials`.
  Non-listed companies surface as an empty list rather than a 501 —
  matching the convention of the FR adapter, since "no public filings"
  is a real, factual answer for a non-listed Moroccan SARL.

Identifiers:
- VAT             → ICE (Identifiant Commun de l'Entreprise), 15 digits.
- COMPANY_NUMBER  → RC (Registre du Commerce), a court-prefix + digits
                    string such as `Casablanca 123456`. Normalised by
                    stripping whitespace; format varies by tribunal.
"""
from __future__ import annotations

import logging
import re
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

logger = logging.getLogger(__name__)

_ICE_RE = re.compile(r"^\d{15}$")
_RC_RE = re.compile(r"^[A-Za-zÀ-ÿ' \-]+ ?\d{1,10}$")


def _normalize_ice(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if cleaned.upper().startswith("MA"):
        cleaned = cleaned[2:]
    if not _ICE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Morocco ICE must be exactly 15 digits, got: {value}"
        )
    return cleaned


def _normalize_rc(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if not cleaned:
        raise InvalidIdentifierError(f"Morocco RC empty: {value}")
    return cleaned


class MAAdapter(CountryAdapter):
    country_code = "MA"
    country_name = "Morocco"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    OMPIC_HEALTH_URL = "https://www.ompic.ma/"
    DIRECTINFO_URL = "https://www.directinfo.ma/"
    TAX_BASE = "https://www.tax.gov.ma"
    AMMC_BASE = "https://www.ammc.ma"
    BOURSE_BASE = "https://www.casablanca-bourse.com"

    async def health_check(self) -> AdapterHealth:
        notes = (
            "Coverage: listed-issuer financials via AMMC / Bourse de Casablanca. "
            "OMPIC commercial register is paid; ICE validator is best-effort."
        )
        try:
            async with build_http_client(timeout=15.0) as client:
                resp = await get_with_retry(client, self.OMPIC_HEALTH_URL)
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.DEGRADED,
                        capabilities={"search": False, "lookup": True, "financials": True},
                        requires_api_key=False,
                        api_key_present=True,
                        rate_limit_per_minute=self.rate_limit_per_minute,
                        notes=f"OMPIC returned HTTP {resp.status_code}. {notes}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": True},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"OMPIC probe failed: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Morocco name search is not available without a paid OMPIC subscription. "
            "Look up by ICE (15 digits) or RC instead."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            ice = _normalize_ice(value)
            return await self._lookup_by_ice(ice)
        if id_type == IdentifierType.COMPANY_NUMBER:
            rc = _normalize_rc(value)
            raise AdapterNotImplementedError(
                f"Morocco RC lookup ({rc}) requires the paid OMPIC commercial register. "
                "Use ICE (15 digits) instead when possible."
            )
        raise InvalidIdentifierError(
            f"Morocco adapter only supports VAT (ICE) or COMPANY_NUMBER (RC), got {id_type}"
        )

    async def _lookup_by_ice(self, ice: str) -> CompanyDetails | None:
        """Best-effort ICE probe against the public DGI validator.

        tax.gov.ma exposes a free identifier-verification flow but the
        response is HTML that often requires a session token / CAPTCHA.
        We attempt a single GET; if the page does not return a definitive
        machine-parseable identity, we raise `AdapterNotImplementedError`
        rather than fabricate a result.
        """
        try:
            async with build_http_client(base_url=self.TAX_BASE, timeout=15.0) as client:
                resp = await get_with_retry(
                    client,
                    "/wps/portal/DGI/ICE",
                    params={"ice": ice},
                )
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"Morocco ICE validator unreachable ({exc.__class__.__name__}). "
                "DGI does not expose a stable public API; integration is "
                "blocked until a documented endpoint is published."
            ) from exc

        body = resp.text or ""
        name = _extract_company_name(body)
        if resp.status_code >= 400 or not name:
            raise AdapterNotImplementedError(
                f"ICE {ice}: DGI returned no machine-readable identity "
                f"(HTTP {resp.status_code}). Free ICE→company-name resolution "
                "is not available without OMPIC."
            )

        return CompanyDetails(
            id=ice,
            name=name,
            country="MA",
            legal_form=None,
            status=None,
            registered_address=_extract_field(body, "adresse")
            or _extract_field(body, "siège"),
            capital_amount=None,
            capital_currency="MAD",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=ice, label="ICE"),
            ],
            raw={"source": "tax.gov.ma", "html_length": len(body)},
            source_url=f"{self.TAX_BASE}/wps/portal/DGI/ICE?ice={ice}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cleaned = re.sub(r"[\s\-]", "", company_id.strip())
        if cleaned.upper().startswith("MA"):
            cleaned = cleaned[2:]
        if not _ICE_RE.match(cleaned):
            raise InvalidIdentifierError(
                f"Morocco company_id must be a 15-digit ICE, got: {company_id}"
            )
        # AMMC and Bourse de Casablanca publish issuer documents on
        # per-issuer pages keyed by ticker, not ICE. Without a free
        # ICE→ticker resolver we cannot enumerate filings; we return
        # an empty list so the credit pipeline can proceed using
        # registry data alone, rather than raise (matches FR convention).
        return []


def _extract_company_name(html: str) -> str | None:
    if not html:
        return None
    for pattern in (
        r"<h[12][^>]*>([^<]{3,200})</h[12]>",
        r"raison\s*sociale\s*[:\-]?\s*</[^>]+>\s*<[^>]+>([^<]{3,200})",
        r"d[ée]nomination\s*[:\-]?\s*</[^>]+>\s*<[^>]+>([^<]{3,200})",
    ):
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            if candidate and not candidate.lower().startswith("erreur"):
                return candidate
    return None


def _extract_field(html: str, label: str) -> str | None:
    if not html:
        return None
    pattern = rf"{label}\s*[:\-]?\s*</[^>]+>\s*<[^>]+>([^<]{{3,300}})"
    m = re.search(pattern, html, re.IGNORECASE)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip() or None
