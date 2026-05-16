"""Paraguay adapter — SET (tax) + BVPASA (stock exchange).

No free, machine-readable national company registry is available. SET
publishes a public RUC validator at https://www.set.gov.py/ but the
endpoint is session/captcha protected and not consumable as a JSON API.
BVPASA (Bolsa de Valores y Productos de Asunción,
https://www.bvpasa.com.py/) publishes annual financial statements for
listed issuers as PDFs, free of charge.

Identifier: RUC (Registro Único de Contribuyentes) — up to 8 digits
followed by a single check digit, formatted as "NNNNNNNN-D".
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
)

_RUC_RE = re.compile(r"^\d{1,8}-\d$")


def _normalize_ruc(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if "-" not in cleaned and cleaned.isdigit() and 2 <= len(cleaned) <= 9:
        # Accept the un-hyphenated form; last digit is the verifier.
        cleaned = f"{cleaned[:-1]}-{cleaned[-1]}"
    if not _RUC_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Paraguay RUC must be up to 8 digits + '-' + verifier, got: {value}"
        )
    return cleaned


class PYAdapter(CountryAdapter):
    country_code = "PY"
    country_name = "Paraguay"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    BVPASA_URL = "https://www.bvpasa.com.py/"

    _NOT_IMPLEMENTED_NOTE = (
        "Paraguay has no free machine-readable company registry. SET RUC "
        "validator is session/captcha-gated; BVPASA covers listed issuers "
        "only and is not searchable by RUC. Implement BVPASA issuer scrape "
        "for listed-only coverage as a follow-up."
    )

    async def health_check(self) -> AdapterHealth:
        notes = self._NOT_IMPLEMENTED_NOTE
        status = AdapterStatus.DEGRADED
        try:
            async with build_http_client(timeout=10.0) as client:
                resp = await get_with_retry(client, self.BVPASA_URL, max_attempts=2)
                if resp.status_code >= 500:
                    status = AdapterStatus.ERROR
                    notes = f"BVPASA returned HTTP {resp.status_code}."
        except Exception as exc:
            status = AdapterStatus.ERROR
            notes = f"BVPASA unreachable: {exc}"[:200]
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={"search": False, "lookup": False, "financials": False},
            requires_api_key=False,
            api_key_present=False,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(self._NOT_IMPLEMENTED_NOTE)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"Paraguay only supports VAT/COMPANY_NUMBER (RUC), got {id_type}"
            )
        _normalize_ruc(value)
        raise AdapterNotImplementedError(self._NOT_IMPLEMENTED_NOTE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # BVPASA issuer-statements scrape is the only legal free path. Until
        # the per-issuer PDF index parser is wired, return an empty list
        # rather than raising — listed-only coverage is sparse and the
        # caller already knows from health_check that financials=False.
        return []
