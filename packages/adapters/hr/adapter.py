"""Croatia adapter — Sudski registar (Court Registry) + FINA RGFI.

Sources (all free, no auth):

- Sudski registar via the public OData feed at https://sudreg-data.gov.hr/api/javni
  Free, public, no API key. Search/filter by OIB (tax/VAT, 11 digits) or
  MBS (court registration number, 9 digits). Returns Pydantic-friendly JSON.
- FINA RGFI (Registar godišnjih financijskih izvještaja) public lookup at
  https://rgfi.fina.hr/IzvjestajiRGFI.action — annual reports (PDF) filed
  by every Croatian company since 2008, free. We discover the per-OIB
  filing-list page and parse the year/document table.

OIB validation uses ISO 7064 MOD 11,10 (the official Croatian checksum)
so we reject malformed identifiers locally before round-tripping.
"""
from __future__ import annotations

import html
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
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_OIB_RE = re.compile(r"^\d{11}$")
_MBS_RE = re.compile(r"^\d{1,9}$")
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _normalize_oib(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "")
    if cleaned.startswith("HR"):
        cleaned = cleaned[2:]
    if not _OIB_RE.match(cleaned):
        raise InvalidIdentifierError(f"HR OIB must be 11 digits, got: {value}")
    if not _oib_checksum_valid(cleaned):
        raise InvalidIdentifierError(f"HR OIB checksum failed: {value}")
    return cleaned


def _oib_checksum_valid(oib: str) -> bool:
    # ISO 7064 MOD 11,10 — the algorithm specified by the Croatian Tax Admin.
    remainder = 10
    for ch in oib[:10]:
        remainder = (remainder + int(ch)) % 10 or 10
        remainder = (remainder * 2) % 11
    control = (11 - remainder) % 10
    return control == int(oib[10])


def _normalize_mbs(value: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if not _MBS_RE.match(cleaned):
        raise InvalidIdentifierError(f"HR MBS must be 1–9 digits, got: {value}")
    return cleaned.zfill(9)


def _strip_tags(text: str) -> str:
    # Replace tags with a space so adjacent <td>2023</td><td>2022</td> doesn't
    # collapse into "20232022" — that would defeat the year boundary scan.
    return html.unescape(_TAG_STRIP_RE.sub(" ", text)).strip()


class HRAdapter(CountryAdapter):
    country_code = "HR"
    country_name = "Croatia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    SUDREG_BASE = "https://sudreg-data.gov.hr/api/javni"
    FINA_BASE = "https://rgfi.fina.hr"
    SUDREG_HTML_BASE = "https://sudreg.pravosudje.hr"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.SUDREG_BASE) as client:
                resp = await get_with_retry(client, "/subjekt_detalji", params={"tip_identifikatora": "oib", "identifikator": "27759560625"})
                if resp.status_code >= 500:
                    raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Sudski registar OData (registry) + FINA RGFI (annual reports, PDF).",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.SUDREG_BASE) as client:
            resp = await get_with_retry(
                client,
                "/subjekt_naziv",
                params={"naziv": name, "samo_valjani": "false", "offset": 0, "limit": limit},
            )
            resp.raise_for_status()
            payload = resp.json()
        items = _extract_list(payload)
        out: list[CompanyMatch] = []
        for item in items[:limit]:
            oib = _coerce_str(item.get("oib"))
            mbs = _coerce_str(item.get("mbs") or item.get("mb"))
            if not oib and not mbs:
                continue
            name_value = _first_name(item)
            idents: list[RegistryIdentifier] = []
            if oib:
                idents.append(RegistryIdentifier(type=IdentifierType.VAT, value=f"HR{oib}", label="OIB"))
            if mbs:
                idents.append(
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER,
                        value=mbs.zfill(9),
                        label="MBS",
                    )
                )
            out.append(
                CompanyMatch(
                    id=oib or mbs.zfill(9),
                    name=name_value,
                    country=self.country_code,
                    identifiers=idents,
                    address=_address_from_subject(item),
                    status=_status_from_subject(item),
                    source_url=self._html_search_url(oib or mbs),
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            oib = _normalize_oib(value)
            params = {"tip_identifikatora": "oib", "identifikator": oib}
        elif id_type == IdentifierType.COMPANY_NUMBER:
            mbs = _normalize_mbs(value)
            params = {"tip_identifikatora": "mbs", "identifikator": mbs}
        else:
            raise InvalidIdentifierError(f"HR only supports VAT (OIB) or COMPANY_NUMBER (MBS), got {id_type}")

        async with build_http_client(base_url=self.SUDREG_BASE) as client:
            resp = await get_with_retry(client, "/subjekt_detalji", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return None
        if isinstance(data, list):
            data = data[0] if data else None
        if not data:
            return None

        oib = _coerce_str(data.get("oib"))
        mbs = _coerce_str(data.get("mbs") or data.get("mb"))
        idents: list[RegistryIdentifier] = []
        if oib:
            idents.append(RegistryIdentifier(type=IdentifierType.VAT, value=f"HR{oib}", label="OIB"))
        if mbs:
            idents.append(
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=mbs.zfill(9),
                    label="MBS",
                )
            )

        return CompanyDetails(
            id=oib or (mbs.zfill(9) if mbs else ""),
            name=_first_name(data),
            country=self.country_code,
            legal_form=_legal_form(data),
            status=_status_from_subject(data),
            incorporation_date=_parse_date(data.get("datum_osnivanja") or data.get("datum_upisa")),
            dissolution_date=_parse_date(data.get("datum_brisanja") or data.get("datum_prestanka")),
            registered_address=_address_from_subject(data),
            capital_amount=_coerce_float(data.get("temeljni_kapital") or data.get("iznos_temeljnog_kapitala")),
            capital_currency=_capital_currency(data),
            nace_codes=_nace_codes(data),
            identifiers=idents,
            raw=data if isinstance(data, dict) else {"items": data},
            source_url=self._html_search_url(oib or mbs),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        oib = _normalize_oib(company_id)
        async with build_http_client(base_url=self.FINA_BASE, timeout=30.0) as client:
            resp = await get_with_retry(
                client,
                "/IzvjestajiRGFI-web/izvjestajiSubjekta.do",
                params={"oib": oib},
            )
            if resp.status_code in (302, 404):
                fallback = await get_with_retry(
                    client,
                    "/IzvjestajiRGFI.action",
                    params={"oib": oib},
                )
                if fallback.status_code == 404:
                    return []
                fallback.raise_for_status()
                page_text = fallback.text
                listing_url = str(fallback.url)
            else:
                resp.raise_for_status()
                page_text = resp.text
                listing_url = str(resp.url)

        years_found = _parse_fina_years(page_text)
        cutoff = max(years_found, default=0) - years if years_found else 0
        filings: list[FinancialFiling] = []
        for year in sorted(years_found, reverse=True):
            if year < cutoff:
                continue
            filings.append(
                FinancialFiling(
                    company_id=oib,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(year, 12, 31),
                    currency="EUR" if year >= 2023 else "HRK",
                    structured_data=None,
                    document_url=None,
                    document_format="pdf",
                    source_url=listing_url,
                )
            )
        return filings

    def _html_search_url(self, identifier: str | None) -> str:
        if not identifier:
            return f"{self.SUDREG_HTML_BASE}/registar/f?p=150"
        return f"{self.SUDREG_HTML_BASE}/registar/f?p=150:28::::28:P28_PRETRAGA:{identifier}"


def _extract_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("value", "items", "data", "results"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [payload]
    return []


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("iznos") or v.get("vrijednost")
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _first_name(item: dict[str, Any]) -> str:
    for key in ("skraceni_naziv", "naziv", "tvrtka", "ime"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            for entry in v:
                if isinstance(entry, dict):
                    inner = entry.get("naziv") or entry.get("ime")
                    if isinstance(inner, str) and inner.strip():
                        return inner.strip()
                elif isinstance(entry, str) and entry.strip():
                    return entry.strip()
        if isinstance(v, dict):
            inner = v.get("naziv") or v.get("ime")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def _legal_form(item: dict[str, Any]) -> str | None:
    v = item.get("pravni_oblik") or item.get("oblik")
    if isinstance(v, dict):
        return _coerce_str(v.get("naziv") or v.get("opis"))
    return _coerce_str(v)


def _status_from_subject(item: dict[str, Any]) -> str | None:
    if item.get("datum_brisanja") or item.get("datum_prestanka"):
        return "ceased"
    valjan = item.get("valjan")
    if isinstance(valjan, bool):
        return "active" if valjan else "ceased"
    return "active" if (item.get("oib") or item.get("mbs")) else None


def _address_from_subject(item: dict[str, Any]) -> str | None:
    sjediste = item.get("sjedista") or item.get("sjediste") or item.get("adresa")
    if isinstance(sjediste, list):
        sjediste = sjediste[0] if sjediste else None
    if not isinstance(sjediste, dict):
        return _coerce_str(sjediste)
    parts = [
        _coerce_str(sjediste.get("ulica")),
        _coerce_str(sjediste.get("kucni_broj")),
        _coerce_str(sjediste.get("postanski_broj") or sjediste.get("postni_broj")),
        _coerce_str(sjediste.get("naselje") or sjediste.get("mjesto")),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _nace_codes(item: dict[str, Any]) -> list[str]:
    raw = item.get("nkd") or item.get("djelatnosti") or item.get("sifra_djelatnosti")
    out: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                code = entry.get("sifra") or entry.get("nkd_sifra")
                if code:
                    out.append(str(code))
            elif entry:
                out.append(str(entry))
    elif isinstance(raw, dict):
        code = raw.get("sifra") or raw.get("nkd_sifra")
        if code:
            out.append(str(code))
    elif raw:
        out.append(str(raw))
    return out


def _capital_currency(item: dict[str, Any]) -> str | None:
    raw = item.get("valuta_temeljnog_kapitala") or item.get("valuta")
    if isinstance(raw, dict):
        return _coerce_str(raw.get("oznaka") or raw.get("sifra"))
    code = _coerce_str(raw)
    if code:
        return code.upper()
    # Croatia switched to EUR on 2023-01-01; pre-2023 capital is HRK on file.
    inc = _parse_date(item.get("datum_osnivanja") or item.get("datum_upisa"))
    if inc and inc.year < 2023:
        return "HRK"
    return "EUR"


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    text = str(s).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_fina_years(html_text: str) -> list[int]:
    """Extract distinct reporting years from a FINA RGFI listing page.

    The listing renders a table of filings with the reporting year in one of
    the columns. We don't parse the table structure — we just collect every
    four-digit year between 1998 and now+1 inside table cells.
    """
    stripped = _strip_tags(html_text)
    years: set[int] = set()
    current_year = date.today().year
    for match in _YEAR_RE.finditer(stripped):
        y = int(match.group(0))
        if 1998 <= y <= current_year:
            years.add(y)
    return sorted(years)
