"""Cambodia adapter — GLEIF registry + CSX filings (both free, no key).

Two free, no-auth, live sources are stitched together:

* GLEIF (api.gleif.org) — the Global LEI index. Cambodian legal entities
  carry their Ministry of Commerce registration number in the LEI
  record's ``entity.registeredAs`` field (e.g. ``00003077`` for ACLEDA
  Bank Plc.), alongside the English legal name and address. This gives a
  name search and a MoC-number lookup keyed on the same identifier the
  Certificate of Incorporation prints. No API key.
  (The Ministry of Commerce's own ``businessregistration.moc.gov.kh``
  public JSON search — used by earlier builds — has been replaced by a
  maintenance page and no longer serves data.)
* csx.com.kh — the Cambodia Securities Exchange. Its website API exposes
  the full listed-company universe and every listed issuer's filed
  annual reports as downloadable PDFs. We resolve a company's CSX symbol
  from its registry name, then emit ``FinancialFiling`` records whose
  ``document_url`` is the exchange's ``file/view-attach`` endpoint — a
  live GET that streams the actual company-specific PDF.

Identifier:
  The MoC company registration number is an 8-digit zero-padded code
  printed on every Certificate of Incorporation (e.g. ``00003077``).
  Cambodian VAT TINs are 9–10-digit codes issued by the General
  Department of Taxation — ``COMPANY_NUMBER`` and ``VAT`` are both
  accepted on lookup; the MoC number is primary.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
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

_MOC_NUMBER_RE = re.compile(r"^\d{1,10}$")
_VAT_TIN_RE = re.compile(r"^\d{9,10}$")
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _normalize_moc_number(value: str) -> str:
    """Strip separators and zero-pad a numeric MoC number to 8 digits.

    Pure-numeric inputs are zero-padded; alphanumeric inputs are rejected
    so we never silently coerce a TIN or a CSX ticker into a MoC slot.
    """
    if value is None:
        raise InvalidIdentifierError("Cambodia MoC number cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("KH"):
        cleaned = cleaned[2:]
    if not _MOC_NUMBER_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Cambodia MoC number must be 1–10 digits; got: {value}"
        )
    return cleaned.zfill(8) if len(cleaned) <= 8 else cleaned


def _normalize_vat_tin(value: str) -> str:
    cleaned = re.sub(r"[\s\-.]", "", str(value or "").strip())
    if cleaned.upper().startswith("KH"):
        cleaned = cleaned[2:]
    if not _VAT_TIN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Cambodia VAT TIN must be 9–10 digits; got: {value}"
        )
    return cleaned


def _parse_kh_date(s: Any) -> date | None:
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _english_name(entity: dict[str, Any]) -> str:
    legal = (entity.get("legalName") or {}).get("name")
    for coll, want in (
        ("otherNames", "ALTERNATIVE_LANGUAGE_LEGAL_NAME"),
        ("transliteratedOtherNames", "PREFERRED_ASCII_TRANSLITERATED_LEGAL_NAME"),
        ("transliteratedOtherNames", "AUTO_ASCII_TRANSLITERATED_LEGAL_NAME"),
    ):
        for o in entity.get(coll) or []:
            if o.get("language") == "en" or o.get("type") == want:
                if o.get("name"):
                    return str(o["name"]).strip()
    if legal:
        return str(legal).strip()
    return ""


def _address_str(entity: dict[str, Any]) -> str | None:
    addr = entity.get("legalAddress") or entity.get("headquartersAddress") or {}
    parts: list[str] = []
    parts.extend(str(x) for x in (addr.get("addressLines") or []) if x)
    for key in ("city", "region", "postalCode", "country"):
        v = addr.get(key)
        if v:
            parts.append(str(v))
    return ", ".join(parts) or None


def _normalize_gleif_status(entity: dict[str, Any]) -> str | None:
    raw = str(entity.get("status") or "").upper()
    if raw == "ACTIVE":
        return "active"
    if raw in ("INACTIVE", "NULL"):
        return "ceased"
    return raw.lower() or None


class KHAdapter(CountryAdapter):
    country_code = "KH"
    country_name = "Cambodia"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    CSX_BASE = "https://csx.com.kh"
    CSX_API = "/api/v1/website"

    def _gleif_headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.api+json"}

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.GLEIF_BASE, headers=self._gleif_headers()
            ) as client:
                resp = await get_with_retry(
                    client,
                    "/lei-records",
                    params={
                        "filter[entity.legalAddress.country]": "KH",
                        "page[size]": 1,
                    },
                )
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"api.gleif.org HTTP {resp.status_code}",
                    )
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
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via GLEIF (entity.registeredAs = MoC number). "
                "Financials via CSX website API: filed annual-report PDFs "
                "for listed issuers; unlisted firms return []."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        records = await self._gleif_search(query, limit)
        matches: list[CompanyMatch] = []
        for rec in records:
            attrs = rec.get("attributes") or {}
            entity = attrs.get("entity") or {}
            lei = attrs.get("lei")
            moc = entity.get("registeredAs")
            display = _english_name(entity)
            if not display or not (moc or lei):
                continue
            identifiers: list[RegistryIdentifier] = []
            if moc:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=str(moc).strip(),
                        label="MoC Number",
                    )
                )
            if lei:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.LEI, value=str(lei), label="LEI"
                    )
                )
            matches.append(
                CompanyMatch(
                    id=str(moc).strip() if moc else str(lei),
                    name=display,
                    country=self.country_code,
                    identifiers=identifiers,
                    address=_address_str(entity),
                    status=_normalize_gleif_status(entity),
                    source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            moc = _normalize_moc_number(value)
            rec = await self._gleif_lookup(
                {"filter[entity.registeredAs]": moc}
            )
            if rec is None and moc.startswith("0"):
                rec = await self._gleif_lookup(
                    {"filter[entity.registeredAs]": moc.lstrip("0") or "0"}
                )
            if rec is None:
                return None
            return self._record_to_details(rec, moc)
        if id_type == IdentifierType.VAT:
            tin = _normalize_vat_tin(value)
            rec = await self._gleif_lookup({"filter[fulltext]": tin})
            if rec is None:
                return None
            entity = (rec.get("attributes") or {}).get("entity") or {}
            moc = entity.get("registeredAs")
            return self._record_to_details(
                rec, _normalize_moc_number(str(moc)) if moc else tin
            )
        raise InvalidIdentifierError(
            f"Cambodia supports COMPANY_NUMBER or VAT, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        moc = _normalize_moc_number(company_id)
        rec = await self._gleif_lookup({"filter[entity.registeredAs]": moc})
        if rec is None:
            return []
        entity = (rec.get("attributes") or {}).get("entity") or {}
        name = _english_name(entity)
        if not name:
            return []

        symbol = await self._csx_resolve_symbol(name)
        if symbol is None:
            return []

        reports = await self._csx_annual_reports(symbol, years)
        filings: list[FinancialFiling] = []
        seen_years: set[int] = set()
        for report in reports:
            year = _report_year(report)
            if year is None or year in seen_years:
                continue
            detail = await self._csx_report_detail(symbol, report["id"])
            document_url = _view_attach_url(self.CSX_BASE, self.CSX_API, detail)
            if not document_url:
                continue
            seen_years.add(year)
            filings.append(
                FinancialFiling(
                    company_id=moc,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="KHR",
                    document_url=document_url,
                    document_format="pdf",
                    source_url=f"{self.CSX_BASE}/en/listed-companies/profile/{symbol}",
                )
            )
            if len(filings) >= years:
                break
        return filings

    async def _gleif_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        params = {
            "filter[entity.legalAddress.country]": "KH",
            "filter[fulltext]": query,
            "page[size]": min(max(limit, 1), 50),
        }
        async with build_http_client(
            base_url=self.GLEIF_BASE, headers=self._gleif_headers()
        ) as client:
            try:
                resp = await get_with_retry(client, "/lei-records", params=params)
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if resp.status_code >= 400:
                return []
            try:
                payload = resp.json()
            except ValueError:
                return []
        data = payload.get("data")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []

    async def _gleif_lookup(self, filters: dict[str, Any]) -> dict[str, Any] | None:
        params = {**filters, "page[size]": 1}
        async with build_http_client(
            base_url=self.GLEIF_BASE, headers=self._gleif_headers()
        ) as client:
            try:
                resp = await get_with_retry(client, "/lei-records", params=params)
            except (httpx.TransportError, httpx.TimeoutException):
                return None
            if resp.status_code >= 400:
                return None
            try:
                payload = resp.json()
            except ValueError:
                return None
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return None

    async def _csx_resolve_symbol(self, name: str) -> str | None:
        target = _slug(name)
        if not target:
            return None
        async with build_http_client(base_url=self.CSX_BASE) as client:
            try:
                resp = await get_with_retry(
                    client, f"{self.CSX_API}/company/stock/list-companies"
                )
            except (httpx.TransportError, httpx.TimeoutException):
                return None
            if resp.status_code >= 400:
                return None
            try:
                rows = (resp.json() or {}).get("data") or []
            except ValueError:
                return None
        best: str | None = None
        for row in rows:
            listed = _slug(str(row.get("nameEn") or ""))
            symbol = str(row.get("symbolEn") or "").strip()
            if not listed or not symbol:
                continue
            if listed == target:
                return symbol
            if best is None and (listed in target or target in listed):
                best = symbol
        return best

    async def _csx_annual_reports(
        self, symbol: str, years: int
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        max_pages = max(1, min(years, 5))
        async with build_http_client(base_url=self.CSX_BASE, timeout=30.0) as client:
            for page in range(1, max_pages + 1):
                try:
                    resp = await client.post(
                        f"{self.CSX_API}/company/stock/annual-reports/{symbol}",
                        params={"page": page},
                        json={},
                    )
                except (httpx.TransportError, httpx.TimeoutException):
                    break
                if resp.status_code >= 400:
                    break
                try:
                    payload = resp.json()
                except ValueError:
                    break
                rows = payload.get("data") or []
                for row in rows:
                    title = str(row.get("title") or "").lower()
                    if "annual report" in title and "quarter" not in title:
                        collected.append(row)
                total_pages = payload.get("totalPages") or 1
                if page >= total_pages:
                    break
        return collected

    async def _csx_report_detail(
        self, symbol: str, report_id: Any
    ) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.CSX_BASE) as client:
            try:
                resp = await get_with_retry(
                    client,
                    f"{self.CSX_API}/company/stock/annual-reports/{symbol}/{report_id}",
                )
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if resp.status_code >= 400:
                return []
            try:
                payload = resp.json()
            except ValueError:
                return []
        data = payload.get("data") or {}
        return data.get("attachFiles") or []

    def _record_to_details(self, rec: dict[str, Any], moc: str) -> CompanyDetails:
        attrs = rec.get("attributes") or {}
        entity = attrs.get("entity") or {}
        lei = attrs.get("lei")
        name = _english_name(entity)
        legal_form = (entity.get("legalForm") or {}).get("id") or (
            entity.get("legalForm") or {}
        ).get("other")

        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=moc, label="MoC Number"
            )
        ]
        if lei:
            identifiers.append(
                RegistryIdentifier(type=IdentifierType.LEI, value=str(lei), label="LEI")
            )

        return CompanyDetails(
            id=moc,
            name=name,
            country="KH",
            legal_form=str(legal_form) if legal_form else None,
            status=_normalize_gleif_status(entity),
            registered_address=_address_str(entity),
            identifiers=identifiers,
            raw=attrs,
            source_url=f"https://search.gleif.org/#/record/{lei}" if lei else None,
        )


def _report_year(report: dict[str, Any]) -> int | None:
    current = datetime.utcnow().year
    title = str(report.get("title") or "")
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(title)]
    years = [y for y in years if 1990 <= y <= current]
    if years:
        return max(years)
    published = _parse_kh_date(report.get("date"))
    if published:
        return published.year - 1
    return None


def _view_attach_url(
    csx_base: str, csx_api: str, attach_files: list[dict[str, Any]]
) -> str | None:
    if not attach_files:
        return None
    english = [a for a in attach_files if str(a.get("boardLang")) == "en"]
    attach = (english or attach_files)[0]
    file_name = attach.get("fileName")
    post_id = attach.get("postId")
    if not file_name or post_id is None:
        return None
    params = {
        "postId": str(post_id),
        "fileName": str(file_name),
        "boardLang": str(attach.get("boardLang") or "en"),
        "boardId": str(attach.get("boardId") or ""),
        "fileOrder": str(attach.get("fileOrder", 0)),
        "originalFileName": str(attach.get("originalFileName") or file_name),
    }
    return f"{csx_base}{csx_api}/file/view-attach?{urlencode(params)}"
