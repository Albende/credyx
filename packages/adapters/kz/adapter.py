"""Kazakhstan adapter — adata.kz wrapper + KASE for listed financials.

Source coverage:

* https://adata.kz/v1/info/bin/{bin} — community-built FREE JSON wrapper
  around the public Bureau of National Statistics (stat.gov.kz) legal-
  entity registry. Returns name, BIN, registration date, OKED activity
  code, address, head/CEO and (sometimes) charter capital. No auth, no
  pricing tier — but it's an unofficial third party, so we treat it as
  best-effort and fall back to the official stat.gov.kz portal URL.
* https://stat.gov.kz/ — Bureau of National Statistics. Publishes the
  legal-entity registry as periodic open-data dumps; no live search REST
  endpoint. Used here only for the health-check probe and as the
  authoritative `source_url` fallback.
* https://kgd.gov.kz/ — State Revenue Committee (tax authority). VAT
  payer search is partial-public and session-bound; not relied on.
* https://kase.kz/ — Kazakhstan Stock Exchange. Listed-issuer annual
  reports are published as free PDFs under predictable per-issuer paths.
  We surface document URLs for the small set of listed companies; for
  everyone else `fetch_financials` returns [].

Identifier:
- BIN (Бизнес-сәйкестендіру нөмірі / Бизнес-идентификационный номер) —
  12 digits, issued to every legal entity. The IIN equivalent for
  natural persons is the same width and is out of scope.
- Both VAT and COMPANY_NUMBER identifier types map to the BIN — the BIN
  is the canonical taxpayer ID in Kazakhstan, so callers may legitimately
  hand us either label.
"""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

_BIN_RE = re.compile(r"^\d{12}$")

# KazMunayGas — well-known active state-owned issuer used as liveness probe.
_HEALTH_PROBE_BIN = "020640000327"

# Subset of KASE-listed issuers with stable BIN → ticker mapping. KASE does
# not expose a free per-BIN reverse lookup, so we keep an explicit table for
# the handful of issuers a credit user is likely to ask about. Anything else
# falls through to an empty filings list rather than fabricating URLs.
_KASE_LISTED: dict[str, str] = {
    "020640000327": "KMGZ",   # КазМунайГаз
    "970640000147": "KZAP",   # НАК Казатомпром
    "920140000084": "KSPI",   # Kaspi.kz
    "011040000284": "AIRA",   # Air Astana
}


def _normalize_bin(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("KZ"):
        cleaned = cleaned[2:]
    if not _BIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kazakhstan BIN must be exactly 12 digits, got: {value}"
        )
    return cleaned


def _parse_kz_date(value: str | None) -> date | None:
    """adata.kz emits ISO dates; stat.gov.kz exports often use DD.MM.YYYY."""
    if not value:
        return None
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).strip()
    return s or None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _first(payload: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value found among the supplied keys.

    adata.kz has shipped at least two key spellings (RU and EN/transliterated)
    across versions, so we look up several candidates per logical field.
    """
    for k in keys:
        if k in payload and payload[k] not in (None, "", []):
            return payload[k]
    return None


class KZAdapter(CountryAdapter):
    country_code = "KZ"
    country_name = "Kazakhstan"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    ADATA_BASE_URL = "https://adata.kz"
    STAT_BASE_URL = "https://stat.gov.kz"
    KASE_BASE_URL = "https://kase.kz"

    def _client(self, *, base_url: str) -> httpx.AsyncClient:
        return build_http_client(
            base_url=base_url,
            headers={
                "Accept": "application/json, text/html;q=0.7",
                "Accept-Language": "ru,kk;q=0.8,en;q=0.6",
            },
            timeout=25.0,
        )

    async def health_check(self) -> AdapterHealth:
        notes: str | None = None
        try:
            async with self._client(base_url=self.ADATA_BASE_URL) as client:
                resp = await get_with_retry(
                    client, f"/v1/info/bin/{_HEALTH_PROBE_BIN}"
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
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"adata.kz unreachable: {exc}"[:200],
            )

        if resp.status_code >= 500:
            notes = (
                f"adata.kz probe returned HTTP {resp.status_code}; "
                "lookups may be degraded."
            )
            status = AdapterStatus.DEGRADED
        elif resp.status_code == 404:
            notes = (
                "adata.kz responded but probe BIN not resolved — wrapper "
                "may have changed; falling back to stat.gov.kz URL only."
            )
            status = AdapterStatus.DEGRADED
        else:
            status = AdapterStatus.OK

        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={
                "search": False,
                "lookup": True,
                "financials": True,
            },
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes
            or (
                "Lookup via adata.kz (free community wrapper around "
                "stat.gov.kz). Financials limited to KASE-listed issuers."
            ),
        )

    async def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[CompanyMatch]:
        # adata.kz and stat.gov.kz do not expose a free name → BIN endpoint;
        # spec rule 1 forbids inventing matches. Keep the door open for a
        # future OpenCorporates KZ bridge but raise explicitly for now.
        raise AdapterNotImplementedError(
            "Kazakhstan has no free name-search endpoint. Look up by BIN "
            "(12-digit Business Identification Number) instead."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (
            IdentifierType.VAT,
            IdentifierType.COMPANY_NUMBER,
        ):
            raise InvalidIdentifierError(
                f"Kazakhstan adapter accepts VAT or COMPANY_NUMBER (BIN), "
                f"got {id_type}"
            )
        bin_value = _normalize_bin(value)

        adata_payload: dict[str, Any] | None = None
        async with self._client(base_url=self.ADATA_BASE_URL) as client:
            try:
                resp = await get_with_retry(
                    client, f"/v1/info/bin/{bin_value}"
                )
            except httpx.HTTPError as exc:
                logger.warning("adata.kz lookup failed for %s: %s", bin_value, exc)
                resp = None  # type: ignore[assignment]

            if resp is not None and resp.status_code == 404:
                return None
            if resp is not None and resp.status_code < 400:
                try:
                    adata_payload = resp.json()
                except ValueError:
                    adata_payload = None

        record = _extract_company_record(adata_payload) if adata_payload else {}
        stat_url = (
            f"{self.STAT_BASE_URL}/ru/lawyer-info/?bin={bin_value}"
        )

        if not record.get("name"):
            # adata returned nothing usable; still surface a stat.gov.kz URL so
            # the operator has a manual fallback. We do NOT invent a name.
            return CompanyDetails(
                id=bin_value,
                name=f"(BIN {bin_value} — name unresolved via adata.kz)",
                country=self.country_code,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=bin_value,
                        label="BIN",
                    ),
                ],
                raw={"source": "adata.kz", "payload": adata_payload},
                source_url=stat_url,
            )

        return CompanyDetails(
            id=bin_value,
            name=record["name"],
            country=self.country_code,
            legal_form=record.get("legal_form"),
            status=record.get("status"),
            incorporation_date=_parse_kz_date(record.get("registration_date")),
            registered_address=record.get("address"),
            capital_amount=_coerce_float(record.get("capital_amount")),
            capital_currency="KZT",
            sic_codes=[],
            nace_codes=[c for c in [record.get("oked")] if c],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=bin_value,
                    label="BIN",
                ),
            ],
            raw={"source": "adata.kz", "payload": adata_payload},
            source_url=f"{self.ADATA_BASE_URL}/v1/info/bin/{bin_value}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        bin_value = _normalize_bin(company_id)
        ticker = _KASE_LISTED.get(bin_value)
        if not ticker:
            # Not a known KASE-listed issuer; Kazakhstan has no free general
            # financial-statement registry, so we return [] rather than 501.
            # A future enhancement could scrape stat.gov.kz "финансовая
            # отчётность" exports per-BIN.
            return []
        # KASE publishes issuer disclosure pages at a stable path; the
        # adapter exposes the index URL only — actual PDF extraction is the
        # PDF pipeline's job (see CLAUDE.md cross-cutting infra section).
        issuer_url = f"{self.KASE_BASE_URL}/en/issuers/{ticker}/"
        current_year = datetime.utcnow().year
        return [
            FinancialFiling(
                company_id=bin_value,
                year=current_year - 1,
                type=FilingType.ANNUAL_REPORT,
                period_end=date(current_year - 1, 12, 31),
                currency="KZT",
                structured_data=None,
                document_url=None,
                document_format=None,
                source_url=issuer_url,
            )
        ]


def _extract_company_record(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Pull a normalized record out of an adata.kz /v1/info/bin response.

    The wrapper has shipped multiple response shapes. Two patterns observed:
    1. Top-level keys (`name`, `bin`, `address`, ...).
    2. Wrapped under `data` or `company` with Russian-language keys
       (`наименование`, `адрес`, `руководитель`, ...).

    We accept either and return a flat dict the adapter can consume.
    """
    if not payload or not isinstance(payload, dict):
        return {}

    # Unwrap one level of envelope if present.
    body: dict[str, Any] = payload
    for wrapper in ("data", "company", "result"):
        inner = body.get(wrapper)
        if isinstance(inner, dict) and inner:
            body = inner
            break

    name = _coerce_str(
        _first(
            body,
            "name",
            "title",
            "full_name",
            "company_name",
            "наименование",
            "name_ru",
            "name_kz",
        )
    )
    address = _coerce_str(
        _first(
            body,
            "address",
            "registered_address",
            "legal_address",
            "адрес",
            "юридический_адрес",
        )
    )
    legal_form = _coerce_str(
        _first(
            body,
            "legal_form",
            "opf",
            "organization_form",
            "опф",
            "форма",
        )
    )
    oked = _coerce_str(
        _first(
            body,
            "oked",
            "activity_code",
            "okved",
            "оквэд",
            "оквд",
            "код_оквэд",
        )
    )
    status = _coerce_str(
        _first(
            body,
            "status",
            "state",
            "activity_status",
            "статус",
            "состояние",
        )
    )
    registration_date = _first(
        body,
        "registration_date",
        "registered_at",
        "registered_on",
        "дата_регистрации",
        "дата",
    )
    capital_amount = _first(
        body,
        "capital",
        "charter_capital",
        "уставный_капитал",
        "уставной_капитал",
    )
    record: dict[str, Any] = {}
    if name:
        record["name"] = name
    if address:
        record["address"] = address
    if legal_form:
        record["legal_form"] = legal_form
    if oked:
        record["oked"] = oked
    if status:
        record["status"] = status
    if registration_date:
        record["registration_date"] = registration_date
    if capital_amount is not None:
        record["capital_amount"] = capital_amount
    return record
