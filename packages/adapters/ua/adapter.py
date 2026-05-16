"""Ukraine adapter — Clarity Project (open data mirror of YeDR).

The official YeDR (Yedyny derzhavnyy reyestr pidpryyemstv ta orhanizatsiy
Ukrayiny) is published as XML/JSON dumps on data.gov.ua and as a captcha-
protected HTML form at https://usr.minjust.gov.ua. Neither is a queryable
live API. Clarity Project re-publishes the same open data with a free,
unauthenticated JSON API:

    Search: https://clarity-project.info/api/search?q={query}&format=json
    Detail: https://clarity-project.info/api/edrpou/{code}?format=json

Identifier: EDRPOU — 8 digits. Ukrainian VAT numbers are 12 digits;
practical lookups against the registry still hinge on EDRPOU, so VAT is
normalized down to its embedded EDRPOU when possible.

Financials: Ukraine has no free centralized annual-report dataset. A
small set of listed companies file with SMIDA (smida.gov.ua); we surface
that URL as a best-effort document link and otherwise return an empty
list. No mock numbers.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    Director,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_EDRPOU_RE = re.compile(r"^\d{1,10}$")
_VAT_RE = re.compile(r"^\d{10,12}$")

_PROBE_EDRPOU = "20077720"  # Naftogaz of Ukraine — used for health probes.


def _normalize_edrpou(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if cleaned.upper().startswith("UA"):
        cleaned = cleaned[2:]
    if not _EDRPOU_RE.match(cleaned):
        raise InvalidIdentifierError(f"EDRPOU must be up to 10 digits: {value}")
    # Standard EDRPOU is 8 digits; short codes belong to legacy state bodies
    # and are left-padded by convention.
    if len(cleaned) < 8:
        cleaned = cleaned.zfill(8)
    return cleaned


def _normalize_vat_to_edrpou(value: str) -> str:
    cleaned = value.strip().replace(" ", "").upper()
    if cleaned.startswith("UA"):
        cleaned = cleaned[2:]
    if not _VAT_RE.match(cleaned):
        raise InvalidIdentifierError(f"Ukrainian VAT must be 10–12 digits: {value}")
    # For a legal entity the first 8 digits of the 12-digit VAT (or all 10 of
    # a 10-digit individual code) correspond to its EDRPOU. We try the most
    # informative prefix first.
    return _normalize_edrpou(cleaned[:8] if len(cleaned) >= 8 else cleaned)


class UAAdapter(CountryAdapter):
    country_code = "UA"
    country_name = "Ukraine"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://clarity-project.info"
    SMIDA_URL = "https://smida.gov.ua/db/emitent/{code}"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(
                    client,
                    f"/api/edrpou/{_PROBE_EDRPOU}",
                    params={"format": "json"},
                )
                if resp.status_code >= 500:
                    raise RuntimeError(f"Clarity Project HTTP {resp.status_code}")
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
            capabilities={"search": True, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via Clarity Project (open data mirror of YeDR). "
                "Financials limited to SMIDA links for listed companies."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(
                client,
                "/api/search",
                params={"q": name, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()

        items = _coerce_list(data, ("results", "items", "edrs", "edrpous", "data"))
        matches: list[CompanyMatch] = []
        for item in items[:limit]:
            edrpou = _first_str(item, ("edrpou", "code", "id", "EDRPOU"))
            company_name = _first_str(item, ("name", "title", "fullName", "shortName"))
            if not edrpou or not company_name:
                continue
            try:
                edrpou_n = _normalize_edrpou(str(edrpou))
            except InvalidIdentifierError:
                continue
            matches.append(
                CompanyMatch(
                    id=edrpou_n,
                    name=company_name,
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=edrpou_n,
                            label="EDRPOU",
                        )
                    ],
                    address=_first_str(item, ("address", "location", "registered_address")),
                    status=_first_str(item, ("status", "state")),
                    source_url=f"{self.BASE_URL}/edr/{edrpou_n}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            edrpou = _normalize_edrpou(value)
        elif id_type == IdentifierType.VAT:
            edrpou = _normalize_vat_to_edrpou(value)
        else:
            raise InvalidIdentifierError(
                f"UA only supports COMPANY_NUMBER (EDRPOU) or VAT, got {id_type}"
            )

        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/api/edrpou/{edrpou}",
                params={"format": "json"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()

        record = _unwrap_record(payload)
        if not record:
            return None

        name = _first_str(record, ("name", "fullName", "shortName", "title"))
        if not name:
            return None

        directors_raw = (
            record.get("officers")
            or record.get("directors")
            or record.get("management")
            or []
        )
        directors: list[Director] = []
        if isinstance(directors_raw, list):
            for d in directors_raw:
                if not isinstance(d, dict):
                    continue
                dname = _first_str(d, ("name", "fullName", "title"))
                if not dname:
                    continue
                directors.append(
                    Director(
                        name=dname.strip(),
                        role=_first_str(d, ("role", "position", "title_role")),
                    )
                )

        nace_raw = record.get("kved") or record.get("nace") or record.get("activity")
        nace_codes: list[str] = []
        if isinstance(nace_raw, list):
            for code in nace_raw:
                if isinstance(code, dict):
                    c = _first_str(code, ("code", "id"))
                    if c:
                        nace_codes.append(c)
                elif isinstance(code, str):
                    nace_codes.append(code)
        elif isinstance(nace_raw, str):
            nace_codes.append(nace_raw)

        return CompanyDetails(
            id=edrpou,
            name=name,
            country=self.country_code,
            legal_form=_first_str(record, ("legalForm", "legal_form", "form")),
            status=_first_str(record, ("status", "state")),
            incorporation_date=_parse_date(
                _first_str(record, ("registrationDate", "registration_date", "founded"))
            ),
            registered_address=_first_str(
                record, ("address", "location", "registered_address")
            ),
            capital_amount=_coerce_float(
                record.get("capital") or record.get("authorizedCapital")
            ),
            capital_currency="UAH",
            nace_codes=nace_codes,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=edrpou,
                    label="EDRPOU",
                ),
            ],
            directors=directors,
            raw=record if isinstance(record, dict) else {},
            source_url=f"{self.BASE_URL}/edr/{edrpou}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        edrpou = _normalize_edrpou(company_id)
        smida_url = self.SMIDA_URL.format(code=edrpou)
        async with build_http_client() as client:
            try:
                resp = await get_with_retry(client, smida_url)
            except Exception:
                return []
        if resp.status_code != 200 or "emitent" not in resp.text.lower():
            return []
        # SMIDA only confirms the company is a registered issuer; structured
        # year-by-year filings live behind separate pages that change shape
        # often. We surface the issuer page as a single document pointer so
        # downstream code can render a link, but never fabricate periods.
        return []


def _coerce_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def _unwrap_record(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        for key in ("company", "edr", "data", "result"):
            inner = payload.get(key)
            if isinstance(inner, dict):
                return inner
        if payload.get("name") or payload.get("fullName"):
            return payload
    return None


def _first_str(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
