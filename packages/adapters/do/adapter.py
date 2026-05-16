"""Dominican Republic adapter — DGII (RNC) + BVRD (listed financials).

Sources:
- DGII (Dirección General de Impuestos Internos): https://www.dgii.gov.do/
  Public RNC consultation page. There is no documented JSON API; the public
  lookup is a session-based ASP.NET WebForm with viewstate plus a downloadable
  daily "DGII_RNC.zip" master file. Per-RNC HTML scraping is brittle and is
  treated as best-effort.
- BVRD (Bolsa de Valores de la República Dominicana): https://www.bvrd.com.do/
  Listed-issuer disclosures are public but not exposed via a stable API.

Identifier: RNC (Registro Nacional del Contribuyente), 9–11 digits. The
classic corporate RNC is 9 digits; cédula-based RNCs can be 11 digits.
"""
from __future__ import annotations

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
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_RNC_RE = re.compile(r"^\d{9,11}$")

_DGII_BASE = "https://www.dgii.gov.do"
_DGII_RNC_PATH = "/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/rnc.aspx"


def _normalize_rnc(value: str) -> str:
    cleaned = re.sub(r"[\s\-\.]", "", value or "")
    if not _RNC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"DO RNC must be 9-11 digits, got: {value!r}"
        )
    return cleaned


class DOAdapter(CountryAdapter):
    country_code = "DO"
    country_name = "Dominican Republic"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    DGII_BASE_URL = _DGII_BASE
    BVRD_BASE_URL = "https://www.bvrd.com.do"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.DGII_BASE_URL) as client:
                resp = await get_with_retry(client, "/")
                if resp.status_code >= 500:
                    raise RuntimeError(f"DGII returned {resp.status_code}")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=False,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"DGII unreachable: {str(exc)[:160]}",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": True, "financials": False},
            requires_api_key=False,
            api_key_present=False,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "DGII has no name-search API; lookup is a best-effort scrape "
                "of the public RNC consultation page. BVRD financials are "
                "available only for listed issuers."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # DGII exposes no public name-search JSON endpoint. The official
        # consultation page is an ASP.NET WebForm with viewstate that requires
        # a browser session, and TOS forbids scraping it at volume. The free
        # alternative is the daily DGII_RNC.zip master file, which is too
        # large to load on the request hot path and belongs to an out-of-band
        # ingestion job (see docs/countries/do.md).
        raise AdapterNotImplementedError(
            "DGII does not expose a name-search API; full-text search over "
            "the DGII_RNC.zip master file is not wired yet."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"DO only supports VAT (RNC) or COMPANY_NUMBER, got {id_type}"
            )
        rnc = _normalize_rnc(value)

        params = {"rnc": rnc}
        source_url = f"{self.DGII_BASE_URL}{_DGII_RNC_PATH}?{httpx.QueryParams(params)}"

        try:
            async with build_http_client(base_url=self.DGII_BASE_URL) as client:
                resp = await get_with_retry(client, _DGII_RNC_PATH, params=params)
        except httpx.HTTPError as exc:
            raise AdapterNotImplementedError(
                f"DGII consultation page unreachable: {exc!s}"
            ) from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise AdapterNotImplementedError(
                f"DGII consultation returned HTTP {resp.status_code}; "
                "scrape pipeline not yet wired."
            )

        parsed = _parse_dgii_rnc_html(resp.text, rnc)
        if parsed is None:
            # The page rendered but the RNC was not found or the page layout
            # differs from what the best-effort scraper expects. We do not
            # invent data — surface as not-found.
            return None

        return CompanyDetails(
            id=rnc,
            name=parsed.get("name") or "",
            country=self.country_code,
            legal_form=parsed.get("legal_form"),
            status=parsed.get("status"),
            registered_address=parsed.get("address"),
            identifiers=[
                RegistryIdentifier(type=IdentifierType.VAT, value=rnc, label="RNC"),
            ],
            raw=parsed.get("raw") or {},
            source_url=source_url,
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Filings are only available for issuers listed on BVRD (Bolsa de
        # Valores RD). BVRD does not expose a stable per-issuer JSON feed; an
        # XBRL/PDF discovery pipeline is required to surface real documents.
        # Per the no-mock-data rule we return an empty list rather than
        # fabricate filings for unlisted companies.
        _ = _normalize_rnc(company_id)
        return []


def _parse_dgii_rnc_html(html: str, rnc: str) -> dict[str, Any] | None:
    """Best-effort extraction of fields from the DGII RNC consultation page.

    The DGII page is a stateful ASP.NET WebForm; a plain GET typically returns
    only the empty search form. We only return a dict when we can positively
    confirm the page shows a record matching `rnc`.
    """
    if not html or rnc not in html:
        return None

    name = _extract_labeled(html, r"Nombre/Raz[oó]n Social")
    status = _extract_labeled(html, r"Estado")
    legal_form = _extract_labeled(html, r"R[eé]gimen de Pagos|Categor[ií]a")
    address = _extract_labeled(html, r"Direcci[oó]n|Domicilio")

    if not name:
        return None

    return {
        "name": _clean(name),
        "status": _clean(status),
        "legal_form": _clean(legal_form),
        "address": _clean(address),
        "raw": {"rnc": rnc},
    }


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = _TAG_RE.sub(" ", value)
    stripped = _WS_RE.sub(" ", stripped).strip()
    return stripped or None


def _extract_labeled(html: str, label_pattern: str) -> str | None:
    """Pick the first cell-after-label match for a DGII consultation row."""
    pattern = re.compile(
        rf"{label_pattern}\s*</[^>]+>\s*<[^>]+>(?P<val>.*?)</",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(html)
    if not m:
        return None
    return m.group("val")
