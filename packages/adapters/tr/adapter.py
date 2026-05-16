"""Türkiye adapter — KAP (Public Disclosure Platform).

Source coverage:

* KAP (Kamuyu Aydınlatma Platformu) — free public JSON feeds covering
  every BIST-listed company. Provides registry-level identifiers (MKK
  sicil, MERSIS, VKN where exposed) and the full disclosure stream
  including annual reports (yıllık) and XBRL filings.
* MERSIS public web is not exposed as a clean JSON API. Without a
  reverse-engineered AngularJS XHR contract we cannot scrape it
  reliably for the MVP, so non-listed companies surface as
  `AdapterNotImplementedError` rather than fabricated data.
* e-Devlet endpoints require a Turkish e-ID (e-Devlet Kapısı) — out of
  scope for the free pipeline.

Identifiers:
- VAT     → VKN (Vergi Kimlik Numarası), 10 digits.
- MERSIS  → 16 digits, sometimes printed as `0710001297-00099`. We
            strip dashes and accept either the 10-digit prefix that
            matches the VKN or the full 16-digit form.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_VKN_RE = re.compile(r"^\d{10}$")
_MERSIS_RE = re.compile(r"^\d{16}$")
_ANNUAL_HINTS = ("yıllık", "yillik", "annual", "yıl sonu", "yil sonu")


def _normalize_vkn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("TR"):
        cleaned = cleaned[2:]
    if not _VKN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Türkiye VKN must be exactly 10 digits, got: {value}"
        )
    return cleaned


def _normalize_mersis(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    if not _MERSIS_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Türkiye MERSIS must be exactly 16 digits, got: {value}"
        )
    return cleaned


def _parse_kap_date(s: str | None) -> date | None:
    """KAP serialises dates as ISO `YYYY-MM-DD` or `DD.MM.YYYY`."""
    if not s:
        return None
    s = s.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        day, month, year = (int(g) for g in m.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


class TRAdapter(CountryAdapter):
    country_code = "TR"
    country_name = "Türkiye"
    identifier_types = [IdentifierType.VAT, IdentifierType.MERSIS]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    KAP_BASE = "https://www.kap.org.tr/en/api"
    KAP_PUBLIC = "https://www.kap.org.tr"

    async def _kap_member_list(self) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.KAP_BASE) as client:
            resp = await get_with_retry(client, "/memberList")
            resp.raise_for_status()
            payload = resp.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("members", "data", "items", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    async def _kap_disclosures(self, member_oid: str) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.KAP_BASE) as client:
            resp = await get_with_retry(
                client, f"/disclosure-list/{member_oid}"
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("disclosures", "data", "items", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.KAP_BASE) as client:
                resp = await get_with_retry(client, "/memberList")
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Coverage limited to BIST-listed companies via KAP; "
            "non-listed entities require MERSIS scrape (not implemented).",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = name.strip().lower()
        if not needle:
            return []
        members = await self._kap_member_list()
        matches: list[CompanyMatch] = []
        for m in members:
            title = (_member_title(m) or "").lower()
            ticker = (_member_ticker(m) or "").lower()
            if needle in title or needle in ticker:
                matches.append(_member_to_match(m))
                if len(matches) >= limit:
                    break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            vkn = _normalize_vkn(value)
            return await self._lookup_listed(vkn=vkn)
        if id_type == IdentifierType.MERSIS:
            mersis = _normalize_mersis(value)
            # MERSIS often embeds the VKN as its leading 10 digits; KAP only
            # publishes VKN, so we match on that prefix as a best-effort.
            return await self._lookup_listed(
                mersis=mersis, vkn_hint=mersis[:10]
            )
        raise InvalidIdentifierError(
            f"Türkiye adapter only supports VAT (VKN) or MERSIS, got {id_type}"
        )

    async def _lookup_listed(
        self,
        *,
        vkn: str | None = None,
        mersis: str | None = None,
        vkn_hint: str | None = None,
    ) -> CompanyDetails | None:
        members = await self._kap_member_list()
        target_vkn = vkn or vkn_hint
        for m in members:
            member_vkn = _member_vkn(m)
            member_mersis = _member_mersis(m)
            if target_vkn and member_vkn and member_vkn == target_vkn:
                return _member_to_details(m, override_mersis=mersis)
            if mersis and member_mersis and member_mersis == mersis:
                return _member_to_details(m, override_mersis=mersis)
        if vkn is not None:
            raise AdapterNotImplementedError(
                f"VKN {vkn} not found among KAP-listed companies. "
                "Non-listed Türkiye registry lookups require MERSIS scraping, "
                "which is not implemented."
            )
        if mersis is not None:
            raise AdapterNotImplementedError(
                f"MERSIS {mersis} not found among KAP-listed companies. "
                "MERSIS scraping is not implemented."
            )
        return None

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cleaned = re.sub(r"[\s\-]", "", company_id.strip())
        if cleaned.upper().startswith("TR"):
            cleaned = cleaned[2:]
        if _VKN_RE.match(cleaned):
            vkn = cleaned
        elif _MERSIS_RE.match(cleaned):
            vkn = cleaned[:10]
        else:
            raise InvalidIdentifierError(
                f"Türkiye company_id must be VKN (10 digits) or MERSIS (16), got: {company_id}"
            )

        members = await self._kap_member_list()
        member = next(
            (m for m in members if _member_vkn(m) == vkn),
            None,
        )
        if member is None:
            raise AdapterNotImplementedError(
                f"VKN {vkn} not listed on KAP; non-listed financials require "
                "MERSIS / Trade Registry scraping, which is not implemented."
            )

        member_oid = _member_oid(member)
        if not member_oid:
            return []

        disclosures = await self._kap_disclosures(member_oid)
        cutoff_year = datetime.utcnow().year - years
        seen: set[str] = set()
        filings: list[FinancialFiling] = []

        for d in disclosures:
            if not _is_annual_report(d):
                continue
            period_end = _disclosure_period_end(d)
            if period_end is None:
                continue
            if period_end.year < cutoff_year:
                continue
            disclosure_oid = str(
                d.get("disclosureIndex")
                or d.get("oid")
                or d.get("disclosureOid")
                or d.get("id")
                or ""
            )
            if not disclosure_oid or disclosure_oid in seen:
                continue
            seen.add(disclosure_oid)
            filings.append(
                FinancialFiling(
                    company_id=vkn,
                    year=period_end.year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="TRY",
                    structured_data=None,
                    document_url=(
                        f"{self.KAP_PUBLIC}/en/Bildirim/{disclosure_oid}"
                    ),
                    document_format="xbrl",
                    source_url=(
                        f"{self.KAP_PUBLIC}/en/sirket-bilgileri/ozet/{member_oid}"
                    ),
                )
            )

        filings.sort(key=lambda f: f.period_end or date.min, reverse=True)
        return filings


def _member_title(m: dict[str, Any]) -> str:
    for key in ("title", "name", "companyName", "memberName", "longName"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _member_ticker(m: dict[str, Any]) -> str:
    for key in ("ticker", "stockCode", "symbol", "code"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _member_oid(m: dict[str, Any]) -> str:
    for key in ("memberOid", "oid", "id", "memberId"):
        v = m.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _member_vkn(m: dict[str, Any]) -> str | None:
    for key in ("vkn", "taxId", "taxNumber", "vergiNo", "vergi"):
        v = m.get(key)
        if v is None:
            continue
        cleaned = re.sub(r"\D", "", str(v))
        if _VKN_RE.match(cleaned):
            return cleaned
    return None


def _member_mersis(m: dict[str, Any]) -> str | None:
    for key in ("mersis", "mersisNo", "mersisNumber"):
        v = m.get(key)
        if v is None:
            continue
        cleaned = re.sub(r"\D", "", str(v))
        if _MERSIS_RE.match(cleaned):
            return cleaned
    return None


def _member_to_match(m: dict[str, Any]) -> CompanyMatch:
    title = _member_title(m)
    ticker = _member_ticker(m)
    vkn = _member_vkn(m)
    mersis = _member_mersis(m)
    member_oid = _member_oid(m)

    identifiers: list[RegistryIdentifier] = []
    if vkn:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.VAT, value=vkn, label="VKN")
        )
    if mersis:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.MERSIS, value=mersis, label="MERSIS"
            )
        )

    return CompanyMatch(
        id=vkn or member_oid or ticker or title,
        name=title or ticker,
        country="TR",
        identifiers=identifiers,
        address=None,
        status="active",
        source_url=(
            f"https://www.kap.org.tr/en/sirket-bilgileri/ozet/{member_oid}"
            if member_oid
            else None
        ),
    )


def _member_to_details(
    m: dict[str, Any],
    *,
    override_mersis: str | None = None,
) -> CompanyDetails:
    title = _member_title(m)
    vkn = _member_vkn(m)
    mersis = _member_mersis(m) or override_mersis
    member_oid = _member_oid(m)

    identifiers: list[RegistryIdentifier] = []
    if vkn:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.VAT, value=vkn, label="VKN")
        )
    if mersis:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.MERSIS, value=mersis, label="MERSIS"
            )
        )

    address = None
    for key in ("address", "headquartersAddress", "registeredAddress"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            address = v.strip()
            break

    website = None
    for key in ("website", "homepage", "webAddress"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            website = v.strip()
            break

    sector_codes: list[str] = []
    for key in ("sectorCode", "industryCode", "nace"):
        v = m.get(key)
        if v:
            sector_codes.append(str(v))

    return CompanyDetails(
        id=vkn or member_oid or title,
        name=title,
        country="TR",
        legal_form=m.get("companyType") or m.get("memberType"),
        status="active",
        registered_address=address,
        capital_amount=None,
        capital_currency="TRY",
        nace_codes=sector_codes,
        identifiers=identifiers,
        website=website,
        raw=m,
        source_url=(
            f"https://www.kap.org.tr/en/sirket-bilgileri/ozet/{member_oid}"
            if member_oid
            else None
        ),
    )


def _is_annual_report(d: dict[str, Any]) -> bool:
    parts: list[str] = []
    for key in (
        "subject",
        "title",
        "disclosureClass",
        "ruleTypeName",
        "templateName",
        "summary",
    ):
        v = d.get(key)
        if isinstance(v, str):
            parts.append(v.lower())
    blob = " ".join(parts)
    if not blob:
        return False
    return any(hint in blob for hint in _ANNUAL_HINTS)


def _disclosure_period_end(d: dict[str, Any]) -> date | None:
    for key in (
        "periodEnd",
        "endDate",
        "financialPeriodEnd",
        "fiscalPeriodEnd",
        "publishDate",
        "disclosureDate",
        "kapPublishDate",
    ):
        v = d.get(key)
        if isinstance(v, str):
            parsed = _parse_kap_date(v)
            if parsed:
                return parsed
    return None
