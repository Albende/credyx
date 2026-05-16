"""Denmark adapter — CVR via distribution.virk.dk.

Source:  Erhvervsstyrelsen ("CVR-permanent") ElasticSearch distribution.
Endpoint: http://distribution.virk.dk/cvr-permanent/virksomhed/_search
Auth:    HTTP Basic (credentials issued free of charge by Erhvervsstyrelsen).
         Sign up: https://datacvr.virk.dk/data/cvr-hjaelp/sadan-soger-du-data-fra-cvr-permanent
Env vars:
    DK_VIRK_USERNAME — Basic auth username
    DK_VIRK_PASSWORD — Basic auth password
Rate:    ~3 req/sec documented; we throttle to 60/min to stay polite.

Identifier: CVR ("CVR-nummer"), 8 digits. VAT is "DK" + CVR.

Annual reports ("regnskaber") are linked from the CVR record. They are
also exposed in a separate JSON catalogue at
https://regnskaber.virk.dk/api/regnskaber?cvr={cvr}. Download URLs in
that feed are public (no auth needed for the document blobs themselves).
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
from packages.adapters._base.http import build_http_client
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_CVR_RE = re.compile(r"^\d{8}$")
_USERNAME_ENV = "DK_VIRK_USERNAME"
_PASSWORD_ENV = "DK_VIRK_PASSWORD"


def _normalize_cvr(value: str, *, allow_vat_prefix: bool = True) -> str:
    """Strip "DK" prefix, whitespace and dots; return canonical 8-digit CVR."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "").replace("-", "")
    if allow_vat_prefix and cleaned.startswith("DK"):
        cleaned = cleaned[2:]
    if not _CVR_RE.match(cleaned):
        raise InvalidIdentifierError(f"Danish CVR must be 8 digits: {value}")
    return cleaned


class DKAdapter(CountryAdapter):
    country_code = "DK"
    country_name = "Denmark"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = _USERNAME_ENV
    rate_limit_per_minute = 60

    SEARCH_URL = "http://distribution.virk.dk/cvr-permanent/virksomhed/_search"
    REGNSKABER_URL = "https://regnskaber.virk.dk/api/regnskaber"

    def __init__(
        self, username: str | None = None, password: str | None = None
    ) -> None:
        self.username = username or os.getenv(_USERNAME_ENV)
        self.password = password or os.getenv(_PASSWORD_ENV)

    def _auth(self) -> httpx.BasicAuth | None:
        if not self.username or not self.password:
            return None
        return httpx.BasicAuth(self.username, self.password)

    def _require_credentials(self) -> None:
        if not self.username:
            raise AdapterError(f"Missing env var {_USERNAME_ENV}")
        if not self.password:
            raise AdapterError(f"Missing env var {_PASSWORD_ENV}")

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        return build_http_client(headers=headers, auth=self._auth())

    async def health_check(self) -> AdapterHealth:
        if not self.username or not self.password:
            missing = _USERNAME_ENV if not self.username else _PASSWORD_ENV
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                notes=f"Set {_USERNAME_ENV} and {_PASSWORD_ENV} to enable. Missing: {missing}.",
            )
        try:
            async with self._client() as client:
                resp = await client.post(
                    self.SEARCH_URL,
                    json={"size": 1, "query": {"match_all": {}}},
                )
                if resp.status_code in (401, 403):
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        requires_api_key=True,
                        api_key_present=True,
                        notes="virk.dk credentials rejected.",
                    )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=True,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        self._require_credentials()
        body = {
            "size": limit,
            "_source": [
                "Vrvirksomhed.cvrNummer",
                "Vrvirksomhed.navne",
                "Vrvirksomhed.virksomhedsstatus",
                "Vrvirksomhed.beliggenhedsadresse",
                "Vrvirksomhed.virksomhedMetadata",
            ],
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "Vrvirksomhed.navne.navn": {
                                    "query": name,
                                    "operator": "and",
                                }
                            }
                        }
                    ]
                }
            },
        }
        hits = await self._search(body)
        out: list[CompanyMatch] = []
        for hit in hits[:limit]:
            v = (hit.get("_source") or {}).get("Vrvirksomhed") or {}
            cvr = _coerce_cvr(v.get("cvrNummer"))
            if not cvr:
                continue
            out.append(
                CompanyMatch(
                    id=cvr,
                    name=_current_name(v) or "",
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER, value=cvr, label="CVR"
                        ),
                        RegistryIdentifier(
                            type=IdentifierType.VAT, value=f"DK{cvr}", label="VAT"
                        ),
                    ],
                    address=_address_from_beliggenhed(v.get("beliggenhedsadresse") or []),
                    status=_current_status(v),
                    source_url=f"https://datacvr.virk.dk/enhed/virksomhed/{cvr}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"DK only supports COMPANY_NUMBER/VAT, got {id_type}"
            )
        cvr = _normalize_cvr(value)
        self._require_credentials()
        body = {
            "size": 1,
            "query": {
                "bool": {
                    "must": [{"term": {"Vrvirksomhed.cvrNummer": int(cvr)}}]
                }
            },
        }
        hits = await self._search(body)
        if not hits:
            return None
        v = (hits[0].get("_source") or {}).get("Vrvirksomhed") or {}
        return _details_from_source(cvr, v)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cvr = _normalize_cvr(company_id)
        self._require_credentials()

        body = {
            "size": 1,
            "_source": ["Vrvirksomhed.cvrNummer", "Vrvirksomhed.regnskaber"],
            "query": {
                "bool": {
                    "must": [{"term": {"Vrvirksomhed.cvrNummer": int(cvr)}}]
                }
            },
        }
        hits = await self._search(body)
        reports: list[dict[str, Any]] = []
        if hits:
            v = (hits[0].get("_source") or {}).get("Vrvirksomhed") or {}
            reports = list(v.get("regnskaber") or [])

        if not reports:
            reports = await self._fetch_regnskaber_catalogue(cvr)

        cutoff_year = datetime.utcnow().year - years
        filings: list[FinancialFiling] = []
        for r in reports:
            period_end = _report_period_end(r)
            year = period_end.year if period_end else _report_year(r)
            if year is None or year < cutoff_year:
                continue
            document_url, document_format = _report_document(r)
            filings.append(
                FinancialFiling(
                    company_id=cvr,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency="DKK",
                    structured_data=None,
                    document_url=document_url,
                    document_format=document_format,
                    source_url=f"https://datacvr.virk.dk/enhed/virksomhed/{cvr}",
                )
            )
        filings.sort(key=lambda f: f.year, reverse=True)
        return filings

    async def _search(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._client() as client:
            resp = await client.post(self.SEARCH_URL, json=body)
            if resp.status_code in (401, 403):
                raise AdapterError("virk.dk credentials rejected")
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise AdapterError(f"virk.dk returned non-JSON payload: {exc}") from exc
        return ((data.get("hits") or {}).get("hits")) or []

    async def _fetch_regnskaber_catalogue(self, cvr: str) -> list[dict[str, Any]]:
        async with build_http_client() as client:
            resp = await client.get(self.REGNSKABER_URL, params={"cvr": cvr})
            if resp.status_code == 404:
                return []
            if resp.status_code >= 400:
                return []
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("regnskaber") or data.get("items") or [])
        return []


def _coerce_cvr(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        s = value.strip()
    else:
        return None
    if not s.isdigit():
        return None
    return s.zfill(8) if len(s) <= 8 else None


def _current_period_pick(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the entry whose period contains today (gyldigTil is null) else the latest."""
    if not items:
        return None
    open_ended = [x for x in items if not x.get("periode", {}).get("gyldigTil")]
    if open_ended:
        return open_ended[-1]
    return items[-1]


def _current_name(v: dict[str, Any]) -> str | None:
    navne = v.get("navne") or []
    pick = _current_period_pick(navne) if isinstance(navne, list) else None
    if pick:
        return pick.get("navn")
    meta = v.get("virksomhedMetadata") or {}
    nyeste = meta.get("nyesteNavn") or {}
    return nyeste.get("navn")


def _current_status(v: dict[str, Any]) -> str | None:
    statuses = v.get("virksomhedsstatus") or []
    pick = _current_period_pick(statuses) if isinstance(statuses, list) else None
    if pick:
        return pick.get("status")
    meta = v.get("virksomhedMetadata") or {}
    return meta.get("sammensatStatus") or (meta.get("nyesteVirksomhedsform") or {}).get("kortBeskrivelse")


def _address_from_beliggenhed(addresses: list[dict[str, Any]]) -> str | None:
    pick = _current_period_pick(addresses) if isinstance(addresses, list) else None
    if not pick:
        return None
    return _format_address(pick)


def _format_address(a: dict[str, Any]) -> str | None:
    if not a:
        return None
    street_parts = [a.get("vejnavn"), a.get("husnummerFra")]
    if a.get("husnummerTil"):
        street_parts.append(f"-{a['husnummerTil']}")
    if a.get("bogstavFra"):
        street_parts.append(a["bogstavFra"])
    line1 = " ".join(str(p) for p in street_parts if p)
    parts = [
        line1 or None,
        a.get("etage"),
        a.get("sidedoer"),
        str(a.get("postnummer") or "") or None,
        a.get("postdistrikt"),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts) or None


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _details_from_source(cvr: str, v: dict[str, Any]) -> CompanyDetails:
    meta = v.get("virksomhedMetadata") or {}
    nyeste_form = meta.get("nyesteVirksomhedsform") or {}
    nyeste_branche = meta.get("nyesteHovedbranche") or {}

    inc = _parse_iso_date(meta.get("stiftelsesDato")) or _parse_iso_date(
        v.get("livsforloeb", [{}])[0].get("periode", {}).get("gyldigFra")
        if v.get("livsforloeb")
        else None
    )
    diss_periode = (meta.get("nyesteLivsforloeb") or {}).get("periode") or {}
    diss = _parse_iso_date(diss_periode.get("gyldigTil"))

    directors: list[Director] = []
    for rel in v.get("deltagerRelation") or []:
        deltager = rel.get("deltager") or {}
        if (deltager.get("enhedstype") or "").upper() != "PERSON":
            continue
        navne = deltager.get("navne") or []
        navn_pick = _current_period_pick(navne) if isinstance(navne, list) else None
        name = (navn_pick or {}).get("navn") if navn_pick else None
        if not name:
            continue
        role_name: str | None = None
        appointed: date | None = None
        resigned: date | None = None
        for org in rel.get("organisationer") or []:
            for medlems in org.get("medlemsData") or []:
                for attrib in medlems.get("attributter") or []:
                    if attrib.get("type") == "FUNKTION":
                        for vrd in attrib.get("vaerdier") or []:
                            role_name = role_name or vrd.get("vaerdi")
                            periode = vrd.get("periode") or {}
                            appointed = appointed or _parse_iso_date(periode.get("gyldigFra"))
                            resigned = resigned or _parse_iso_date(periode.get("gyldigTil"))
        directors.append(
            Director(
                name=name.strip(),
                role=role_name,
                appointed_on=appointed,
                resigned_on=resigned,
            )
        )

    sic = nyeste_branche.get("branchekode")
    nace_codes = [str(sic)] if sic else []

    return CompanyDetails(
        id=cvr,
        name=_current_name(v) or "",
        country="DK",
        legal_form=nyeste_form.get("langBeskrivelse") or nyeste_form.get("kortBeskrivelse"),
        status=_current_status(v),
        incorporation_date=inc,
        dissolution_date=diss,
        registered_address=_address_from_beliggenhed(v.get("beliggenhedsadresse") or []),
        capital_amount=None,
        capital_currency="DKK",
        nace_codes=nace_codes,
        identifiers=[
            RegistryIdentifier(type=IdentifierType.COMPANY_NUMBER, value=cvr, label="CVR"),
            RegistryIdentifier(type=IdentifierType.VAT, value=f"DK{cvr}", label="VAT"),
        ],
        directors=directors,
        raw=v,
        source_url=f"https://datacvr.virk.dk/enhed/virksomhed/{cvr}",
    )


def _report_period_end(r: dict[str, Any]) -> date | None:
    period_end = (
        r.get("regnskabsperiodeSlutDato")
        or r.get("regnskabsperiode_slut")
        or (r.get("regnskabsperiode") or {}).get("slutDato")
        or (r.get("regnskabsperiode") or {}).get("gyldigTil")
    )
    return _parse_iso_date(period_end)


def _report_year(r: dict[str, Any]) -> int | None:
    y = r.get("regnskabsperiodeAar") or r.get("year")
    if isinstance(y, int):
        return y
    if isinstance(y, str) and y.isdigit():
        return int(y)
    return None


def _report_document(r: dict[str, Any]) -> tuple[str | None, str | None]:
    url = r.get("dokumentUrl") or r.get("pdfUrl") or r.get("xbrlUrl") or r.get("url")
    if not url:
        for doc in r.get("dokumenter") or []:
            url = doc.get("dokumentUrl") or doc.get("url")
            if url:
                fmt = (doc.get("dokumentMimeType") or "").lower()
                if "xbrl" in fmt or url.endswith(".xml") or url.endswith(".xbrl"):
                    return url, "xbrl"
                if "pdf" in fmt or url.lower().endswith(".pdf"):
                    return url, "pdf"
                return url, fmt or None
    if not url:
        return None, None
    lower = url.lower()
    if lower.endswith(".xbrl") or lower.endswith(".xml"):
        return url, "xbrl"
    return url, "pdf"
