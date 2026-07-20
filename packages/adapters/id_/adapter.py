"""Indonesia adapter — IDX (Indonesia Stock Exchange).

Free, no-auth, listed-company coverage sourced entirely from IDX
(https://www.idx.co.id). Two public JSON endpoints power the adapter:

* ``/primary/ListedCompany/GetCompanyProfiles`` — the full directory of
  listed issuers (~960 companies). Each record carries the trading
  ``KodeEmiten`` (ticker), ``NamaEmiten`` (legal name), ``NPWP`` (the tax
  ID), registered address, sector and contact fields. This powers
  ``search_by_name`` and ``lookup_by_identifier``.
* ``/primary/ListedCompany/GetFinancialReport`` — per-issuer, per-year
  audited financial reports. Each result lists real downloadable PDF
  attachments hosted under ``/Portals/0/StaticData/...``. This powers
  ``fetch_financials`` with genuine filing metadata + document URLs.

Both endpoints sit behind Cloudflare, which rejects the plain httpx TLS
fingerprint with a 403 HTML challenge, so requests are routed through the
repo's ``fetch_with_bot_bypass`` (FlareSolverr) helper, which returns the
JSON payload wrapped in an HTML ``<pre>`` shell.

Identifiers:
  * **NPWP** (Nomor Pokok Wajib Pajak) — the 15-digit Indonesian tax ID.
    Canonical display form ``XX.XXX.XXX.X-XXX.XXX``; digits are the source
    of truth. Mapped to ``IdentifierType.VAT`` and used as the primary
    identifier because IDX publishes it for every listed issuer.
  * **IDX ticker** (KodeEmiten) — the 2–5 letter exchange code. Mapped to
    ``IdentifierType.OTHER`` and used as the adapter-local stable id.

Coverage is listed companies only. Unlisted Indonesian firms have no free
official financial source (AHU/OSS extracts and OJK data sit behind paid
or session-gated products the MVP does not consume), so a name search that
matches nothing on IDX returns ``[]`` and an NPWP that is not a listed
issuer resolves to ``None``.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import fetch_with_bot_bypass
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

_NPWP_RE = re.compile(r"^\d{15}$")
_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")

_PROFILES_TTL_SECONDS = 3600.0


def _normalize_npwp(value: str) -> str:
    """Strip dots, dashes, spaces; require exactly 15 digits.

    Accepts raw 15-digit strings and the ``XX.XXX.XXX.X-XXX.XXX`` display
    form, plus an optional leading ``ID`` prefix.
    """
    if value is None:
        raise InvalidIdentifierError("Indonesia NPWP cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("ID"):
        cleaned = cleaned[2:]
    if not _NPWP_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Indonesia NPWP must be exactly 15 digits, got: {value}"
        )
    return cleaned


def _format_npwp(npwp: str) -> str:
    """Return the canonical ``XX.XXX.XXX.X-XXX.XXX`` display form."""
    return f"{npwp[0:2]}.{npwp[2:5]}.{npwp[5:8]}.{npwp[8:9]}-{npwp[9:12]}.{npwp[12:15]}"


def _norm_ticker(value: str) -> str | None:
    cleaned = str(value or "").strip().upper()
    if cleaned.startswith("IDX:"):
        cleaned = cleaned[4:].strip()
    return cleaned if _TICKER_RE.match(cleaned) else None


def _pick(r: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return None


def _npwp_digits(raw: Any) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"[\s\-.]", "", str(raw).strip())
    return digits if _NPWP_RE.match(digits) else None


def _extract_json(body: str) -> Any:
    """Parse an IDX JSON payload from either a raw body or FlareSolverr HTML.

    FlareSolverr renders the endpoint in a headless browser, so the JSON
    arrives wrapped in ``<html>…<pre>{json}</pre>…</html>`` with the usual
    HTML entity escaping.
    """
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        m = re.search(r"<pre[^>]*>(.*)</pre>", body, re.DOTALL)
        if not m:
            raise
        return json.loads(html.unescape(m.group(1)))


class IDAdapter(CountryAdapter):
    country_code = "ID"
    country_name = "Indonesia"
    identifier_types = [IdentifierType.VAT, IdentifierType.OTHER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    IDX_BASE = "https://www.idx.co.id"

    _profiles_cache: list[dict[str, Any]] | None = None
    _profiles_at: float = 0.0

    async def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self.IDX_BASE}{path}?{urllib.parse.urlencode(params)}"
        body, status, _ = await fetch_with_bot_bypass(url, timeout=40.0)
        if status != 200:
            raise RuntimeError(f"IDX {path} returned HTTP {status}")
        return _extract_json(body)

    async def _profiles(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._profiles_cache is not None and now - self._profiles_at < _PROFILES_TTL_SECONDS:
            return self._profiles_cache
        payload = await self._get_json(
            "/primary/ListedCompany/GetCompanyProfiles",
            {"start": 0, "length": 9999, "emitenType": "s"},
        )
        data = payload.get("data", []) if isinstance(payload, dict) else []
        self._profiles_cache = data
        self._profiles_at = now
        return data

    def _profile_url(self, ticker: str) -> str:
        return f"{self.IDX_BASE}/en-us/listed-companies/company-profiles/?kodeEmiten={ticker}"

    def _reports_url(self, ticker: str) -> str:
        return (
            f"{self.IDX_BASE}/en-us/listed-companies/"
            f"financial-statements-and-annual-report/?kodeEmiten={ticker}"
        )

    def _identifiers(self, profile: dict[str, Any]) -> list[RegistryIdentifier]:
        ids: list[RegistryIdentifier] = []
        npwp = _npwp_digits(profile.get("NPWP"))
        if npwp:
            ids.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=_format_npwp(npwp), label="NPWP"
                )
            )
        ticker = str(profile.get("KodeEmiten") or "").strip().upper()
        if ticker:
            ids.append(
                RegistryIdentifier(
                    type=IdentifierType.OTHER, value=ticker, label="IDX ticker"
                )
            )
        return ids

    def _match(self, profile: dict[str, Any]) -> CompanyMatch:
        ticker = str(profile.get("KodeEmiten") or "").strip().upper()
        address = _pick(profile, "Alamat")
        return CompanyMatch(
            id=ticker,
            name=str(profile.get("NamaEmiten") or ticker).strip(),
            country=self.country_code,
            identifiers=self._identifiers(profile),
            address=re.sub(r"\s*\n\s*", ", ", address.strip()) if address else None,
            status="Listed",
            source_url=self._profile_url(ticker),
        )

    def _details(self, profile: dict[str, Any]) -> CompanyDetails:
        ticker = str(profile.get("KodeEmiten") or "").strip().upper()
        name = str(profile.get("NamaEmiten") or ticker).strip()
        address = _pick(profile, "Alamat")
        listed_on = None
        raw_listed = _pick(profile, "TanggalPencatatan")
        if raw_listed:
            try:
                listed_on = date.fromisoformat(str(raw_listed)[:10])
            except ValueError:
                listed_on = None
        return CompanyDetails(
            id=ticker,
            name=name,
            country=self.country_code,
            legal_form="Perseroan Terbatas Tbk" if name.upper().endswith("TBK") else None,
            status="Listed",
            registered_address=re.sub(r"\s*\n\s*", ", ", address.strip()) if address else None,
            identifiers=self._identifiers(profile),
            website=_pick(profile, "Website"),
            phone=_pick(profile, "Telepon"),
            email=_pick(profile, "Email"),
            raw={
                "sector": _pick(profile, "Sektor"),
                "sub_sector": _pick(profile, "SubSektor"),
                "industry": _pick(profile, "Industri"),
                "sub_industry": _pick(profile, "SubIndustri"),
                "listing_board": _pick(profile, "PapanPencatatan"),
                "listing_date": listed_on.isoformat() if listed_on else None,
                "share_registrar": _pick(profile, "BAE"),
            },
            source_url=self._profile_url(ticker),
        )

    async def health_check(self) -> AdapterHealth:
        try:
            profiles = await self._profiles()
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
            status=AdapterStatus.OK if profiles else AdapterStatus.DEGRADED,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                f"IDX directory reachable ({len(profiles)} listed issuers). "
                "Coverage is listed companies only."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = str(name or "").strip().lower()
        if not query:
            return []
        profiles = await self._profiles()
        exact: list[CompanyMatch] = []
        partial: list[CompanyMatch] = []
        for profile in profiles:
            company = str(profile.get("NamaEmiten") or "").lower()
            ticker = str(profile.get("KodeEmiten") or "").lower()
            if query == ticker:
                exact.append(self._match(profile))
            elif query in company:
                partial.append(self._match(profile))
        return (exact + partial)[:limit]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            npwp = _normalize_npwp(value)
            profiles = await self._profiles()
            for profile in profiles:
                if _npwp_digits(profile.get("NPWP")) == npwp:
                    return self._details(profile)
            return None
        if id_type == IdentifierType.OTHER:
            ticker = _norm_ticker(value)
            if not ticker:
                raise InvalidIdentifierError(
                    f"Indonesia IDX ticker must be 2-5 letters, got: {value}"
                )
            profiles = await self._profiles()
            for profile in profiles:
                if str(profile.get("KodeEmiten") or "").strip().upper() == ticker:
                    return self._details(profile)
            return None
        raise InvalidIdentifierError(
            f"Indonesia supports VAT (NPWP) or OTHER (IDX ticker), got {id_type}"
        )

    async def _resolve_ticker(self, company_id: str) -> str | None:
        cleaned = str(company_id or "").strip()
        ticker = _norm_ticker(cleaned)
        if ticker:
            return ticker
        digits = re.sub(r"[\s\-.]", "", cleaned)
        if _NPWP_RE.match(digits):
            for profile in await self._profiles():
                if _npwp_digits(profile.get("NPWP")) == digits:
                    return str(profile.get("KodeEmiten") or "").strip().upper()
            return None
        raise InvalidIdentifierError(
            "Indonesia company_id must be an IDX ticker, an 'IDX:{ticker}' hint, "
            f"or a 15-digit NPWP; got: {company_id}"
        )

    @staticmethod
    def _statement_attachment(attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
        pdfs = [a for a in attachments if str(a.get("File_Type", "")).lower() == ".pdf"]
        if not pdfs:
            return None
        for needle in ("financialstatement", "lkfs", "laporan keuangan", "annualreport"):
            for a in pdfs:
                if needle in str(a.get("File_Name", "")).lower():
                    return a
        return pdfs[0]

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        ticker = await self._resolve_ticker(company_id)
        if not ticker:
            return []

        filings: list[FinancialFiling] = []
        latest = datetime.utcnow().year - 1
        for year in range(latest, latest - years, -1):
            payload = await self._get_json(
                "/primary/ListedCompany/GetFinancialReport",
                {
                    "indexFrom": 0,
                    "pageSize": 12,
                    "year": year,
                    "reportType": "rdf",
                    "EmitenType": "s",
                    "periode": "audit",
                    "kodeEmiten": ticker,
                    "SortColumn": "KodeEmiten",
                    "SortOrder": "asc",
                },
            )
            if not isinstance(payload, dict) or payload.get("ResultCount", 0) < 1:
                continue
            for result in payload.get("Results", []):
                attachment = self._statement_attachment(result.get("Attachments", []))
                if not attachment:
                    continue
                document_url = self.IDX_BASE + urllib.parse.quote(
                    str(attachment["File_Path"]), safe="/"
                )
                filings.append(
                    FinancialFiling(
                        company_id=ticker,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="IDR",
                        document_url=document_url,
                        document_format="pdf",
                        source_url=self._reports_url(ticker),
                    )
                )
                break
        return filings
