"""Russia adapter — Federal Tax Service (FNS) public registries.

Source coverage:

* https://egrul.nalog.ru/ — Unified State Register of Legal Entities /
  Individual Entrepreneurs (ЕГРЮЛ / ЕГРИП). Public name + INN + OGRN
  search. Two-step protocol: POST a form, get a token, GET the result
  JSON by token.
* https://bo.nalog.ru/ — State Information Resource for Accounting
  Reports (ГИРБО). Annual balance sheets and P&L filed with the FNS
  since 2019. Free PDF / Excel downloads.

Both are FREE government endpoints, no API key required.

Identifiers (Russian numbering):

- **INN** (Идентификационный номер налогоплательщика, Taxpayer
  Identification Number). 10 digits for legal entities, 12 digits for
  individuals / sole proprietors. Modulo-11 check digit(s). Mapped to
  `IdentifierType.VAT` because INN is the VAT registration ID.
- **OGRN** (Основной государственный регистрационный номер, Primary
  State Registration Number). 13 digits for legal entities (OGRNIP =
  15 digits for sole proprietors; the FNS portal returns both via the
  same search). Mapped to `IdentifierType.COMPANY_NUMBER`.
- **KPP** (Код причины постановки на учёт, Reason-for-Registration
  Code). 9 digits, paired with INN to identify a branch. Returned in
  the registry payload but not accepted as a lookup identifier.

Sanctions context: many Russian legal entities listed at egrul.nalog.ru
are subject to EU / UK / US sanctions. The registry data itself is
factual; downstream consumers MUST run OpenSanctions screening before
any credit decision.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any

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

logger = logging.getLogger(__name__)

_INN_RE = re.compile(r"^\d{10}$|^\d{12}$")
_OGRN_RE = re.compile(r"^\d{13}$|^\d{15}$")

# Sberbank PAO — the largest Russian bank, always present in EGRUL; safe
# liveness probe.
_HEALTH_PROBE_INN = "7707083893"

# Per Mod-11 INN checksum spec the position weights are fixed by the
# Federal Tax Service. See order ММВ-7-6/435@ of 2012.
_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _checksum(digits: str, weights: tuple[int, ...]) -> int:
    total = sum(int(d) * w for d, w in zip(digits, weights, strict=True))
    return (total % 11) % 10


def _valid_inn(value: str) -> bool:
    if len(value) == 10:
        return _checksum(value[:9], _INN10_WEIGHTS) == int(value[9])
    if len(value) == 12:
        return (
            _checksum(value[:10], _INN12_WEIGHTS_1) == int(value[10])
            and _checksum(value[:11], _INN12_WEIGHTS_2) == int(value[11])
        )
    return False


def _normalize_inn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("RU"):
        cleaned = cleaned[2:]
    if not _INN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Russian INN must be 10 (legal entity) or 12 (individual) digits, got: {value}"
        )
    if not _valid_inn(cleaned):
        raise InvalidIdentifierError(
            f"Russian INN failed Mod-11 checksum: {value}"
        )
    return cleaned


def _normalize_ogrn(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("RU"):
        cleaned = cleaned[2:]
    if not _OGRN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Russian OGRN must be 13 (legal entity) or 15 (sole proprietor) digits, got: {value}"
        )
    return cleaned


def _parse_ru_date(value: str | None) -> date | None:
    """EGRUL renders dates in either ISO or DD.MM.YYYY form."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    # Order matters: "недейств" must be matched before "действ" because
    # the inactive form contains the active stem as a substring.
    if any(
        t in low
        for t in (
            "недейств",
            "ликвидир",
            "прекращ",
            "исключ",
            "приостан",
            "liquidated",
            "inactive",
        )
    ):
        return "inactive"
    if any(t in low for t in ("действ", "зарегистрир", "active")):
        return "active"
    return raw.strip() or None


def _first_str(obj: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return None


def _extract_name(rec: dict[str, Any]) -> str | None:
    return _first_str(rec, ("n", "name", "full_name", "fn", "namec", "namep"))


def _extract_address(rec: dict[str, Any]) -> str | None:
    return _first_str(rec, ("a", "adr", "address", "addr"))


def _extract_director(rec: dict[str, Any]) -> str | None:
    # EGRUL row JSON uses `g` for the head's name and `j`/`tj` for title.
    return _first_str(rec, ("g", "head", "director"))


def _extract_legal_form(rec: dict[str, Any]) -> str | None:
    return _first_str(rec, ("opf", "legal_form", "form"))


def _extract_okved(rec: dict[str, Any]) -> list[str]:
    raw = rec.get("ok") or rec.get("okved") or rec.get("okveds")
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if isinstance(raw, list):
        codes: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                codes.append(item.strip())
            elif isinstance(item, dict):
                code = _first_str(item, ("code", "k", "okved"))
                if code:
                    codes.append(code)
        return codes
    return []


class RUAdapter(CountryAdapter):
    country_code = "RU"
    country_name = "Russia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    EGRUL_BASE_URL = "https://egrul.nalog.ru"
    EGRUL_SEARCH_PATH = "/"
    EGRUL_RESULT_PATH = "/search-result/{token}"

    BO_BASE_URL = "https://bo.nalog.ru"
    BO_SEARCH_PATH = "/nbo/organizations/search"
    BO_REPORTS_PATH = "/nbo/organizations/{org_id}/bfo/"
    BO_FILE_PATH = "/nbo/bfo/{report_id}/transformation-file/"

    def _client(self, *, base_url: str | None = None) -> httpx.AsyncClient:
        return build_http_client(
            base_url=base_url or self.EGRUL_BASE_URL,
            headers={
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
                "Accept-Language": "ru,en;q=0.5",
                # egrul.nalog.ru reads requests as form-encoded AJAX from
                # the React SPA; setting Origin/Referer keeps the gateway
                # from short-circuiting to a 400.
                "Origin": "https://egrul.nalog.ru",
                "Referer": "https://egrul.nalog.ru/",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=25.0,
        )

    async def _egrul_query(self, client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
        """Two-step EGRUL search: POST → token → GET search-result/{token}."""
        post_resp = await client.post(
            self.EGRUL_SEARCH_PATH,
            data={
                "vyp3CaptchaToken": "",
                "page": "",
                "query": query,
                "region": "",
                "PreventChromeAutocomplete": "",
            },
        )
        if post_resp.status_code == 404:
            return []
        post_resp.raise_for_status()
        body: Any
        try:
            body = post_resp.json()
        except ValueError:
            return []
        token = None
        if isinstance(body, dict):
            token = body.get("t") or body.get("token")
        if not token:
            return []

        # Result is computed server-side; poll briefly for readiness.
        records: list[dict[str, Any]] = []
        for _ in range(6):
            result_resp = await get_with_retry(
                client, self.EGRUL_RESULT_PATH.format(token=token)
            )
            if result_resp.status_code == 404:
                return []
            result_resp.raise_for_status()
            try:
                payload = result_resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                rows = payload.get("rows") or payload.get("items") or []
                if isinstance(rows, list) and rows:
                    records = [r for r in rows if isinstance(r, dict)]
                    break
                # status flag — 1 == still building; back off briefly.
                if payload.get("status") in (1, "1"):
                    await asyncio.sleep(0.6)
                    continue
                if "rows" in payload:  # explicit empty result
                    break
            elif isinstance(payload, list):
                records = [r for r in payload if isinstance(r, dict)]
                break
            await asyncio.sleep(0.4)
        return records

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._client() as client:
                records = await self._egrul_query(client, _HEALTH_PROBE_INN)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        if not records:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": True, "lookup": True, "financials": True},
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "egrul.nalog.ru reachable but probe INN returned no rows; "
                    "schema may have shifted or geo-block engaged."
                ),
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup + name search via egrul.nalog.ru; financials via "
                "bo.nalog.ru (PDF/Excel since 2019)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        async with self._client() as client:
            records = await self._egrul_query(client, query)

        matches: list[CompanyMatch] = []
        for rec in records[:limit]:
            ogrn = _first_str(rec, ("o", "ogrn", "ogrnip"))
            inn = _first_str(rec, ("i", "inn"))
            company_name = _extract_name(rec)
            if not company_name or not (ogrn or inn):
                continue
            identifiers: list[RegistryIdentifier] = []
            if ogrn:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=ogrn,
                        label="OGRN" if len(ogrn) == 13 else "OGRNIP",
                    )
                )
            if inn:
                identifiers.append(
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=inn,
                        label="INN",
                    )
                )
            primary_id = inn or ogrn or ""
            matches.append(
                CompanyMatch(
                    id=primary_id,
                    name=company_name,
                    country=self.country_code,
                    identifiers=identifiers,
                    address=_extract_address(rec),
                    status=_classify_status(_first_str(rec, ("st", "status"))),
                    source_url=(
                        f"{self.EGRUL_BASE_URL}/?query={primary_id}"
                        if primary_id
                        else None
                    ),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            normalized = _normalize_inn(value)
        elif id_type == IdentifierType.COMPANY_NUMBER:
            normalized = _normalize_ogrn(value)
        else:
            raise InvalidIdentifierError(
                f"Russia adapter supports VAT (INN) or COMPANY_NUMBER (OGRN), got {id_type}"
            )

        async with self._client() as client:
            records = await self._egrul_query(client, normalized)

        if not records:
            return None
        # EGRUL may return several rows when a search term matches branches;
        # the first row is always the legal entity itself for an exact INN/OGRN.
        record = records[0]
        name = _extract_name(record)
        if not name:
            return None

        inn = _first_str(record, ("i", "inn")) or (
            normalized if id_type == IdentifierType.VAT else None
        )
        ogrn = _first_str(record, ("o", "ogrn", "ogrnip")) or (
            normalized if id_type == IdentifierType.COMPANY_NUMBER else None
        )
        kpp = _first_str(record, ("p", "kpp"))

        identifiers: list[RegistryIdentifier] = []
        if ogrn:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=ogrn,
                    label="OGRN" if len(ogrn) == 13 else "OGRNIP",
                )
            )
        if inn:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT,
                    value=inn,
                    label="INN",
                )
            )
        if kpp:
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.OTHER,
                    value=kpp,
                    label="KPP",
                )
            )

        director_name = _extract_director(record)
        directors = []
        if director_name:
            from packages.shared.models import Director

            directors = [
                Director(
                    name=director_name,
                    role=_first_str(record, ("j", "tj", "head_title")),
                )
            ]

        primary_id = inn or ogrn or normalized
        return CompanyDetails(
            id=primary_id,
            name=name,
            country=self.country_code,
            legal_form=_extract_legal_form(record),
            status=_classify_status(_first_str(record, ("st", "status"))),
            incorporation_date=_parse_ru_date(
                _first_str(record, ("r", "reg_date", "registration_date"))
            ),
            dissolution_date=_parse_ru_date(
                _first_str(record, ("e", "term_date", "dissolution_date"))
            ),
            registered_address=_extract_address(record),
            capital_amount=None,
            capital_currency="RUB",
            nace_codes=_extract_okved(record),
            identifiers=identifiers,
            directors=directors,
            raw={"source": "egrul.nalog.ru", "row": record},
            source_url=f"{self.EGRUL_BASE_URL}/?query={primary_id}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """Pull annual accounting reports from bo.nalog.ru by INN.

        The portal indexes by INN, not OGRN; if an OGRN is supplied we
        resolve it to INN via an EGRUL round-trip first.
        """
        cleaned = re.sub(r"[\s\-]", "", company_id.strip()).upper()
        if cleaned.startswith("RU"):
            cleaned = cleaned[2:]
        if _INN_RE.match(cleaned):
            inn = _normalize_inn(cleaned)
        elif _OGRN_RE.match(cleaned):
            ogrn = _normalize_ogrn(cleaned)
            async with self._client() as client:
                rows = await self._egrul_query(client, ogrn)
            inn_str = None
            if rows:
                inn_str = _first_str(rows[0], ("i", "inn"))
            if not inn_str:
                return []
            inn = _normalize_inn(inn_str)
        else:
            raise InvalidIdentifierError(
                f"Russia fetch_financials needs an INN or OGRN, got: {company_id}"
            )

        async with build_http_client(
            base_url=self.BO_BASE_URL,
            headers={
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
                "Accept-Language": "ru,en;q=0.5",
                "Referer": "https://bo.nalog.ru/",
            },
            timeout=25.0,
        ) as client:
            search_resp = await get_with_retry(
                client,
                self.BO_SEARCH_PATH,
                params={"query": inn, "page": "0"},
            )
            if search_resp.status_code == 404:
                return []
            search_resp.raise_for_status()
            try:
                search_payload = search_resp.json()
            except ValueError:
                return []

            orgs = (
                search_payload.get("content")
                if isinstance(search_payload, dict)
                else None
            )
            if not isinstance(orgs, list) or not orgs:
                return []
            org = orgs[0]
            org_id = org.get("id") if isinstance(org, dict) else None
            if not org_id:
                return []

            reports_resp = await get_with_retry(
                client, self.BO_REPORTS_PATH.format(org_id=org_id)
            )
            if reports_resp.status_code == 404:
                return []
            reports_resp.raise_for_status()
            try:
                reports_payload = reports_resp.json()
            except ValueError:
                return []

        if not isinstance(reports_payload, list):
            return []

        filings: list[FinancialFiling] = []
        cutoff_year = datetime.utcnow().year - years
        for item in reports_payload:
            if not isinstance(item, dict):
                continue
            period = item.get("period") or item.get("year")
            try:
                year = int(str(period)[:4]) if period else None
            except (TypeError, ValueError):
                year = None
            if year is None or year < cutoff_year:
                continue
            report_id = item.get("id")
            period_end = _parse_ru_date(item.get("dateUpdate") or item.get("date"))
            if period_end is None and year is not None:
                period_end = date(year, 12, 31)
            document_url = None
            if report_id is not None:
                document_url = (
                    f"{self.BO_BASE_URL}"
                    f"{self.BO_FILE_PATH.format(report_id=report_id)}"
                )
            filings.append(
                FinancialFiling(
                    company_id=inn,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="RUB",
                    structured_data=None,
                    document_url=document_url,
                    document_format="pdf",
                    source_url=f"{self.BO_BASE_URL}/organizations-card/{org_id}",
                )
            )
        # bo.nalog.ru returns newest-first occasionally; normalize to
        # descending year for predictable consumer ordering.
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings
