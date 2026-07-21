"""Türkiye adapter — KAP (Public Disclosure Platform).

Source coverage:

* KAP (Kamuyu Aydınlatma Platformu) rebuilt its site on Next.js in 2025 and
  removed the old open JSON feeds (`/en/api/memberList`,
  `/en/api/disclosure-list/{oid}`). The current free surfaces are:

  - ``POST /en/api/search/combined`` — company/fund full-text search
    (name and ticker only; tax numbers are NOT indexed).
  - ``GET /en/sirket-bilgileri/ozet/{mkkMemberOid}`` — company summary page
    whose server-rendered RSC payload embeds a ``memberDetail`` JSON object
    (title, VKN/taxNo, trade registry number, paid capital, city, ticker).
  - ``POST /en/api/disclosure/members/byCriteria`` — disclosure query
    (max 1-year date window per request); ``disclosureClass="FR"`` with
    ``ruleType="Annual"`` marks annual financial reports. Each disclosure
    carries a ``disclosureIndex``; ``GET /en/api/BildirimPdf/{index}``
    returns that specific filing as a downloadable ``application/pdf``.

* Because the rebuilt platform publishes tax numbers only on per-company
  pages, VKN/MERSIS → company resolution is no longer possible without
  scanning every member. Search results therefore carry the MKK member OID
  as the company id, and lookups by raw VKN/MERSIS raise
  ``AdapterNotImplementedError`` unless KAP's search happens to resolve
  them. Details fetched by OID still include the VKN.
* MERSIS public web is not exposed as a clean JSON API; e-Devlet endpoints
  require a Turkish e-ID — both out of scope for the free pipeline.

Identifiers:
- VAT     → VKN (Vergi Kimlik Numarası), 10 digits.
- MERSIS  → 16 digits, sometimes printed as `0710001297-00099`.
- KAP member OID → 32-char hex, returned by search and accepted by
  lookup/financials regardless of declared identifier type.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, fetch_with_bot_bypass
from packages.adapters.tr import gleif_tr
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
_MEMBER_OID_RE = re.compile(r"^[0-9a-fA-F]{32}$")

# KAP's /en search endpoint only matches ASCII-folded text.
_TURKISH_FOLD = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")


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


class TRAdapter(CountryAdapter):
    country_code = "TR"
    country_name = "Türkiye"
    identifier_types = [IdentifierType.VAT, IdentifierType.MERSIS, IdentifierType.LEI]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 60

    KAP_BASE = "https://www.kap.org.tr"

    async def _kap_search(self, keyword: str) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.KAP_BASE) as client:
            resp = await client.post(
                "/en/api/search/combined",
                json={
                    "keyword": keyword.translate(_TURKISH_FOLD),
                    "discClass": "ALL",
                    "lang": "en",
                    "channel": "WEB",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        for category in payload if isinstance(payload, list) else []:
            if category.get("category") != "companyOrFunds":
                continue
            results = category.get("results") or []
            return [
                r
                for r in results
                if isinstance(r, dict)
                and r.get("searchType") == "C"
                and r.get("memberOrFundOid")
            ]
        return []

    async def _member_detail(self, member_oid: str) -> dict[str, Any] | None:
        page, status, _source = await fetch_with_bot_bypass(
            f"{self.KAP_BASE}/en/sirket-bilgileri/ozet/{member_oid}",
            timeout=30.0,
        )
        if status == 404:
            return None
        if status >= 400:
            raise AdapterError(f"KAP company page HTTP {status} for {member_oid}")
        detail = _extract_member_detail(page)
        if detail is None:
            raise AdapterError(
                f"KAP company page for {member_oid} no longer embeds memberDetail "
                "— page format changed."
            )
        return detail

    async def _disclosures(
        self, member_oid: str, from_date: date, to_date: date
    ) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.KAP_BASE) as client:
            resp = await client.post(
                "/en/api/disclosure/members/byCriteria",
                json={
                    "fromDate": from_date.isoformat(),
                    "toDate": to_date.isoformat(),
                    "memberType": "IGS",
                    "mkkMemberOidList": [member_oid],
                    "inactiveMkkMemberOidList": [],
                    "disclosureClass": "FR",
                    "subjectList": [],
                    "isLate": "",
                    "mainSector": "",
                    "sector": "",
                    "subSector": "",
                    "marketOid": "",
                    "index": "",
                    "bdkReview": "",
                    "bdkMemberOidList": [],
                    "year": "",
                    "term": "",
                    "ruleType": "",
                    "period": "",
                    "fromSrc": False,
                    "srcCategory": "",
                    "disclosureIndexList": [],
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        return [d for d in payload if isinstance(d, dict)] if isinstance(payload, list) else []

    async def health_check(self) -> AdapterHealth:
        try:
            results = await self._kap_search("türk")
            if not results:
                raise RuntimeError("KAP combined search returned no companies")
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
            notes="Coverage limited to KAP members (BIST-listed companies); "
            "lookups key on the KAP member OID — raw VKN/MERSIS are not "
            "searchable on the rebuilt platform.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        needle = name.strip()
        if not needle:
            return []
        results = await self._kap_search(needle)
        matches = self._kap_matches(results, limit)
        # Private (non-listed) companies never appear on KAP — always layer
        # in GLEIF (carries the MERSIS number for TR entities), then rank
        # hits that actually contain the query above KAP's fuzzy noise.
        try:
            gleif = await gleif_tr.search_tr(needle, limit=limit)
        except Exception as exc:
            logger.warning("GLEIF TR search failed: %s", exc)
            gleif = []
        seen = {m.name.casefold() for m in matches}
        matches.extend(g for g in gleif if g.name.casefold() not in seen)

        folded_query = needle.translate(_TURKISH_FOLD).casefold()

        def relevance(m: CompanyMatch) -> int:
            folded = m.name.translate(_TURKISH_FOLD).casefold()
            return 0 if folded_query in folded else 1

        matches.sort(key=relevance)
        return matches[:limit]

    def _kap_matches(
        self, results: list[dict[str, Any]], limit: int
    ) -> list[CompanyMatch]:
        matches: list[CompanyMatch] = []
        for r in results[:limit]:
            member_oid = str(r["memberOrFundOid"])
            title = (r.get("searchValue") or "").strip()
            ticker = (r.get("cmpOrFundCode") or "").strip().upper()
            if not title:
                continue
            identifiers: list[RegistryIdentifier] = []
            if ticker:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.OTHER, value=ticker, label="BIST ticker"
                    )
                )
            matches.append(
                CompanyMatch(
                    id=member_oid,
                    name=title,
                    country="TR",
                    identifiers=identifiers,
                    address=None,
                    status="active",
                    source_url=f"{self.KAP_BASE}/en/sirket-bilgileri/ozet/{member_oid}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.MERSIS, IdentifierType.LEI):
            raise InvalidIdentifierError(
                f"Türkiye adapter only supports VAT (VKN), MERSIS or LEI, got {id_type}"
            )
        cleaned = re.sub(r"[\s\-]", "", value.strip())
        if _MEMBER_OID_RE.match(cleaned):
            return await self._details_by_oid(cleaned)
        if id_type == IdentifierType.LEI or gleif_tr.is_lei(cleaned):
            return await gleif_tr.lookup_lei(cleaned)
        if id_type == IdentifierType.VAT:
            number = _normalize_vkn(value)
        else:
            number = _normalize_mersis(value)
            details = await gleif_tr.lookup_mersis(number)
            if details is not None:
                return details
        # KAP's search only indexes titles/tickers, but numbers occasionally
        # resolve (e.g. pasted into a title); try once before giving up.
        results = await self._kap_search(number)
        if results:
            return await self._details_by_oid(str(results[0]["memberOrFundOid"]))
        raise AdapterNotImplementedError(
            f"KAP's rebuilt platform does not index tax numbers, so "
            f"{id_type.value} {number} cannot be resolved directly. Resolve "
            "the company via search_by_name and use the returned KAP member "
            "OID; company details fetched that way include the VKN."
        )

    async def _details_by_oid(self, member_oid: str) -> CompanyDetails | None:
        detail = await self._member_detail(member_oid)
        if detail is None:
            return None
        return _member_detail_to_details(detail, member_oid, self.KAP_BASE)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cleaned = re.sub(r"[\s\-]", "", company_id.strip())
        if _MEMBER_OID_RE.match(cleaned):
            member_oid = cleaned
            vkn: str | None = None
        else:
            details = await self.lookup_by_identifier(
                IdentifierType.VAT if not _MERSIS_RE.match(cleaned) else IdentifierType.MERSIS,
                cleaned,
            )
            if details is None:
                return []
            member_oid = details.raw.get("mkkMemberOid") or details.id
            vkn = _detail_vkn(details.raw)

        today = datetime.utcnow().date()
        filings: list[FinancialFiling] = []
        seen: set[int] = set()
        window_end = today
        # The disclosure API rejects date spans over one year, so page
        # backwards in yearly windows. One extra window catches annual
        # reports published the year after their fiscal year.
        for _ in range(years + 1):
            window_start = window_end - timedelta(days=364)
            disclosures = await self._disclosures(member_oid, window_start, window_end)
            for d in disclosures:
                if (d.get("ruleType") or "").strip().lower() != "annual":
                    continue
                if not (d.get("subject") or "").strip().lower().startswith("financial report"):
                    continue
                fiscal_year = d.get("year")
                index = d.get("disclosureIndex")
                if not isinstance(fiscal_year, int) or not isinstance(index, int):
                    continue
                if index in seen or fiscal_year < today.year - years:
                    continue
                seen.add(index)
                filings.append(
                    FinancialFiling(
                        company_id=vkn or member_oid,
                        year=fiscal_year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(fiscal_year, 12, 31),
                        currency="TRY",
                        structured_data=None,
                        document_url=f"{self.KAP_BASE}/en/api/BildirimPdf/{index}",
                        document_format="pdf",
                        source_url=f"{self.KAP_BASE}/en/Bildirim/{index}",
                    )
                )
            window_end = window_start - timedelta(days=1)

        filings.sort(key=lambda f: f.period_end or date.min, reverse=True)
        return filings


def _extract_member_detail(page: str) -> dict[str, Any] | None:
    """Pull the escaped ``memberDetail`` JSON object out of the RSC payload.

    The Next.js flight data embeds it inside a JS string literal, so quotes
    arrive as ``\\"``; we brace-match the escaped text and JSON-decode twice.
    """
    marker = page.find('memberDetail\\":')
    if marker < 0:
        return None
    start = page.find("{", marker)
    if start < 0:
        return None
    depth = 0
    for i in range(start, min(len(page), start + 20000)):
        ch = page[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                escaped = page[start : i + 1]
                try:
                    unescaped = json.loads('"' + escaped + '"')
                    parsed = json.loads(unescaped)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _detail_vkn(detail: dict[str, Any]) -> str | None:
    raw = re.sub(r"\D", "", str(detail.get("taxNo") or ""))
    return raw if _VKN_RE.match(raw) else None


def _member_detail_to_details(
    detail: dict[str, Any], member_oid: str, base: str
) -> CompanyDetails:
    title = (detail.get("kapMemberTitle") or "").strip()
    vkn = _detail_vkn(detail)
    ticker = (detail.get("stockCode") or "").strip()

    identifiers: list[RegistryIdentifier] = []
    if vkn:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.VAT, value=vkn, label="VKN")
        )
    trade_reg = (detail.get("tradeRegNo") or "").strip()
    if trade_reg:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.OTHER, value=trade_reg, label="Trade registry no"
            )
        )
    if ticker:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.OTHER, value=ticker, label="BIST ticker"
            )
        )

    address_bits = [
        (detail.get("tradeRegOffice") or "").strip(),
        (detail.get("cityName") or "").strip(),
    ]
    address = ", ".join(dict.fromkeys(b for b in address_bits if b)) or None

    capital = detail.get("paidCapital")

    return CompanyDetails(
        id=member_oid,
        name=title,
        country="TR",
        legal_form=detail.get("kapMemberType"),
        status="active" if (detail.get("kapMemberState") or "A") == "A" else "inactive",
        incorporation_date=_parse_trade_reg_date(detail.get("tradeRegDate")),
        registered_address=address,
        capital_amount=float(capital) if isinstance(capital, (int, float)) else None,
        capital_currency="TRY",
        nace_codes=[],
        identifiers=identifiers,
        raw=detail,
        source_url=f"{base}/en/sirket-bilgileri/ozet/{member_oid}",
    )


def _parse_trade_reg_date(value: Any) -> date | None:
    if not value:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", str(value).strip())
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
