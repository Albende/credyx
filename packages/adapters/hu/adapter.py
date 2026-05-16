"""Hungary adapter — VIES (VAT) + e-beszamolo (annual reports).

Free public sources only:
- VIES REST: https://ec.europa.eu/taxation_customs/vies/rest-api/ms/HU/vat/{vat}
  Returns JSON {countryCode, vatNumber, valid, name, address, ...}. No auth.
- e-beszamolo (im.gov.hu): public annual report repository — every Hungarian
  company files balance sheets / annual reports here for FREE. The site is
  session+CSRF based, so we can't reliably scrape search/filings from a clean
  HTTP client without a browser. We expose deep-link source_urls for the UI
  and raise AdapterNotImplementedError where structured data isn't available
  without a browser pool.

The paid e-cégjegyzék / opten / ceginfo are out of scope (MVP rule).

Identifiers:
- Cégjegyzékszám (Company Registry Number): NN-NN-NNNNNN (2-2-6 digits).
- Adószám (Tax ID): 11 digits, first 8 are the "törzsszám" used in VAT.
- VAT: "HU" + first 8 digits of Adószám.
"""
from __future__ import annotations

import re
from typing import Any

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

# Cégjegyzékszám: 10 digits split as 2-2-6.
_CEGJEGYZEKSZAM_RE = re.compile(r"^(\d{2})-?(\d{2})-?(\d{6})$")
# Hungarian Adószám / VAT törzsszám: 8 digits.
_HU_VAT_DIGITS_RE = re.compile(r"^\d{8}$")
# Full Adószám: 11 digits (8 + 1 VAT code + 2 area code).
_ADOSZAM_RE = re.compile(r"^\d{11}$")


def _normalize_cegjegyzekszam(value: str) -> str:
    """Normalize Cégjegyzékszám to canonical NN-NN-NNNNNN form."""
    cleaned = value.strip().replace(" ", "")
    m = _CEGJEGYZEKSZAM_RE.match(cleaned)
    if not m:
        raise InvalidIdentifierError(
            f"Hungarian Cégjegyzékszám must be NN-NN-NNNNNN (10 digits): {value}"
        )
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _normalize_hu_vat(value: str) -> str:
    """Normalize a Hungarian VAT to its 8-digit törzsszám form.

    Accepts ``HU12345678``, ``12345678``, or a full 11-digit Adószám (the
    first 8 digits are the VAT törzsszám).
    """
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("HU"):
        cleaned = cleaned[2:]
    if _ADOSZAM_RE.match(cleaned):
        cleaned = cleaned[:8]
    if not _HU_VAT_DIGITS_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Hungarian VAT must be HU + 8 digits (or 11-digit Adószám): {value}"
        )
    return cleaned


class HUAdapter(CountryAdapter):
    country_code = "HU"
    country_name = "Hungary"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    VIES_BASE_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api"
    EBESZAMOLO_BASE_URL = "https://e-beszamolo.im.gov.hu"
    # A known-valid HU VAT (OTP Bank) used for liveness probe.
    HEALTH_PROBE_VAT = "10537914"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.VIES_BASE_URL) as client:
                resp = await get_with_retry(
                    client, f"/ms/HU/vat/{self.HEALTH_PROBE_VAT}"
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("isValid", body.get("valid")):
                    raise RuntimeError("VIES returned invalid for known HU VAT")
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
            capabilities={"search": False, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup by VAT via VIES works. Cégjegyzékszám lookup links to "
                "e-beszamolo; name search and structured financials require a "
                "browser pool (e-beszamolo is session+CSRF based, paid "
                "e-cégjegyzék is out of scope)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # The only free Hungarian name-search surfaces (e-beszamolo, e-cégjegyzék)
        # require a session/CSRF token and cannot be queried from a clean httpx
        # client. Raise rather than return mock results.
        raise AdapterNotImplementedError(
            "Hungarian name search requires a browser pool against "
            "e-beszamolo.im.gov.hu (session + CSRF). Not in MVP scope."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            return await self._lookup_by_vat(value)
        if id_type == IdentifierType.COMPANY_NUMBER:
            return self._lookup_by_cegjegyzekszam(value)
        raise InvalidIdentifierError(
            f"HU only supports VAT and COMPANY_NUMBER, got {id_type}"
        )

    async def _lookup_by_vat(self, value: str) -> CompanyDetails | None:
        vat = _normalize_hu_vat(value)
        async with build_http_client(base_url=self.VIES_BASE_URL) as client:
            resp = await get_with_retry(client, f"/ms/HU/vat/{vat}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        if not data.get("isValid", data.get("valid")):
            return None
        # VIES name/address fields can be empty strings or "---" for some MS;
        # treat those as missing.
        raw_name = (data.get("name") or "").strip()
        raw_addr = (data.get("address") or "").strip()
        name = "" if raw_name in {"", "---"} else raw_name
        addr = None if raw_addr in {"", "---"} else _clean_address(raw_addr)
        return CompanyDetails(
            id=vat,
            name=name,
            country="HU",
            registered_address=addr,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=f"HU{vat}", label="Adószám (VAT)"
                ),
            ],
            raw=data,
            source_url=(
                f"https://ec.europa.eu/taxation_customs/vies/?vat=HU{vat}"
            ),
        )

    def _lookup_by_cegjegyzekszam(self, value: str) -> CompanyDetails:
        cj = _normalize_cegjegyzekszam(value)
        # Without a browser session, we can't pull the registry record. We
        # surface a deep-link to e-beszamolo so the UI is still useful, and
        # mark the name as unknown rather than inventing one.
        return CompanyDetails(
            id=cj,
            name="(name not available; e-beszamolo lookup requires browser session)",
            country="HU",
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=cj,
                    label="Cégjegyzékszám",
                ),
            ],
            source_url=(
                f"https://e-beszamolo.im.gov.hu/oldal/beszamolo_kereses"
                f"?cegjegyzekszam={cj}"
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # e-beszamolo distributes FREE annual report PDFs, but the search and
        # download flow requires a CSRF token + session cookie. Returning [] now
        # rather than raising lets callers proceed with VIES-only data; the
        # CompanyDetails.source_url points at e-beszamolo for manual access.
        # Switch to a real implementation once the browser-pool infra lands.
        return []


def _clean_address(addr: str) -> str:
    # VIES often returns the Hungarian address with embedded newlines and
    # double spaces — collapse to a single line.
    collapsed = re.sub(r"\s+", " ", addr.replace("\n", " ").replace("\r", " "))
    return collapsed.strip()
