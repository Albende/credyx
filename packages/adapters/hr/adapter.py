"""Croatia adapter — Sudski registar (Court Registry) open-data API.

Sources:

- Sudski registar open-data REST API at https://sudreg-data.gov.hr/api/javni.
  Since the 2024 portal revamp the API requires OAuth2 client-credentials:
  register (free) at https://sudreg-data.gov.hr/, then set
  ``HR_SUDREG_CLIENT_ID`` and ``HR_SUDREG_CLIENT_SECRET``. Tokens come from
  ``POST /api/oauth/token`` (HTTP basic auth, ``grant_type=client_credentials``)
  and are valid for 6 hours.
  Endpoints used: ``/javni/subjekti?tvrtka_naziv=…`` (name search) and
  ``/javni/detalji_subjekta?tip_identifikatora=oib|mbs&identifikator=…``.
- FINA RGFI (annual reports) retired its anonymous public lookup
  (``rgfi.fina.hr/IzvjestajiRGFI.action`` now 404s; JavnaObjava-web requires
  an interactive login). The sudreg ``/javni/gfi`` endpoint only exposes GFI
  document metadata as bulk snapshots, not per-company queries, so
  ``fetch_financials`` raises ``AdapterNotImplementedError`` instead of
  fabricating filings.

OIB validation uses ISO 7064 MOD 11,10 (the official Croatian checksum)
so we reject malformed identifiers locally before round-tripping.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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
    RegistryIdentifier,
)

_OIB_RE = re.compile(r"^\d{11}$")
_MBS_RE = re.compile(r"^\d{1,9}$")

_CLIENT_ID_ENV = "HR_SUDREG_CLIENT_ID"
_CLIENT_SECRET_ENV = "HR_SUDREG_CLIENT_SECRET"


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


class HRAdapter(CountryAdapter):
    country_code = "HR"
    country_name = "Croatia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = True
    api_key_env = _CLIENT_ID_ENV
    rate_limit_per_minute = 30

    SUDREG_BASE = "https://sudreg-data.gov.hr/api"
    SUDREG_HTML_BASE = "https://sudreg.pravosudje.hr"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.client_id = client_id or os.getenv(_CLIENT_ID_ENV)
        self.client_secret = client_secret or os.getenv(_CLIENT_SECRET_ENV)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _require_credentials(self) -> None:
        if not self.client_id or not self.client_secret:
            raise AdapterError(
                "Croatian sudreg open-data API requires OAuth2 client "
                "credentials since the 2024 portal revamp. Register (free) at "
                "https://sudreg-data.gov.hr/ and set "
                f"{_CLIENT_ID_ENV} / {_CLIENT_SECRET_ENV}."
            )

    async def _get_token(self) -> str:
        self._require_credentials()
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        async with build_http_client(base_url=self.SUDREG_BASE) as client:
            resp = await client.post(
                "/oauth/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
            )
        if resp.status_code == 401:
            raise AdapterError(
                "sudreg-data.gov.hr rejected the OAuth client credentials "
                f"({_CLIENT_ID_ENV} / {_CLIENT_SECRET_ENV})."
            )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise AdapterError(
                f"sudreg-data.gov.hr token response missing access_token: {payload}"
            )
        expires_in = float(payload.get("expires_in") or 21600)
        self._token = token
        self._token_expires_at = time.monotonic() + expires_in - 60
        return token

    async def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        token = await self._get_token()
        async with build_http_client(
            base_url=self.SUDREG_BASE,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await get_with_retry(client, path, params=params)
            if resp.status_code == 404:
                return None
            if resp.status_code == 401:
                # Token may have been revoked server-side; refetch once.
                self._token = None
                token = await self._get_token()
                resp = await get_with_retry(
                    client,
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 404:
                    return None
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> AdapterHealth:
        key_present = bool(self.client_id and self.client_secret)
        if not key_present:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.BLOCKED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "sudreg-data.gov.hr requires free OAuth2 registration; set "
                    f"{_CLIENT_ID_ENV} / {_CLIENT_SECRET_ENV}."
                ),
            )
        try:
            data = await self._get_json(
                "/javni/detalji_subjekta",
                {"tip_identifikatora": "oib", "identifikator": "27759560625"},
            )
            if data is None:
                raise RuntimeError("probe OIB not found")
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Sudski registar open-data API (OAuth2). FINA RGFI public "
                "lookup retired — no per-company financials."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        payload = await self._get_json(
            "/javni/subjekti",
            {
                "tvrtka_naziv": name,
                "only_active": "false",
                "offset": 0,
                "limit": limit,
            },
        )
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
        params["expand_relations"] = "true"

        data = await self._get_json("/javni/detalji_subjekta", params)
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
            capital_amount=_capital_amount(data),
            capital_currency=_capital_currency(data),
            nace_codes=_nace_codes(data),
            identifiers=idents,
            raw=data if isinstance(data, dict) else {"items": data},
            source_url=self._html_search_url(oib or mbs),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        _normalize_oib(company_id)
        raise AdapterNotImplementedError(
            "Croatian annual reports are no longer freely queryable per "
            "company: FINA retired the anonymous RGFI lookup and the sudreg "
            "open-data /javni/gfi endpoint only serves bulk snapshots of GFI "
            "document metadata."
        )

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
    for key in ("skracena_tvrtka", "tvrtka", "skraceni_naziv", "naziv", "ime"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            for entry in v:
                if isinstance(entry, dict):
                    inner = entry.get("ime") or entry.get("naziv")
                    if isinstance(inner, str) and inner.strip():
                        return inner.strip()
                elif isinstance(entry, str) and entry.strip():
                    return entry.strip()
        if isinstance(v, dict):
            inner = v.get("ime") or v.get("naziv")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def _legal_form(item: dict[str, Any]) -> str | None:
    v = item.get("pravni_oblik") or item.get("oblik")
    if isinstance(v, dict):
        return _coerce_str(v.get("naziv") or v.get("opis") or v.get("vrsta"))
    return _coerce_str(v)


def _status_from_subject(item: dict[str, Any]) -> str | None:
    if item.get("datum_brisanja") or item.get("datum_prestanka"):
        return "ceased"
    for key in ("postupak", "status"):
        v = item.get(key)
        if isinstance(v, str) and "brisan" in v.lower():
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
        _coerce_str(sjediste.get("kucni_podbroj")),
        _coerce_str(sjediste.get("postanski_broj") or sjediste.get("postni_broj")),
        _coerce_str(sjediste.get("naziv_naselja") or sjediste.get("naselje") or sjediste.get("mjesto")),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _nace_codes(item: dict[str, Any]) -> list[str]:
    raw = (
        item.get("pretezite_djelatnosti")
        or item.get("nkd")
        or item.get("djelatnosti")
        or item.get("sifra_djelatnosti")
    )
    out: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                code = entry.get("sifra") or entry.get("nkd_sifra") or entry.get("djelatnost_sifra")
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


def _capital_block(item: dict[str, Any]) -> Any:
    raw = item.get("temeljni_kapitali") or item.get("temeljni_kapital") or item.get("iznos_temeljnog_kapitala")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    return raw


def _capital_amount(item: dict[str, Any]) -> float | None:
    return _coerce_float(_capital_block(item))


def _capital_currency(item: dict[str, Any]) -> str | None:
    block = _capital_block(item)
    if isinstance(block, dict):
        raw = block.get("valuta")
        if isinstance(raw, dict):
            raw = raw.get("oznaka") or raw.get("sifra")
        code = _coerce_str(raw)
        if code:
            return code.upper()
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
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None
