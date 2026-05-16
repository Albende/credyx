"""Poland adapter — KRS (Ministry of Justice) + Biała Lista (Ministry of Finance).

Free, no auth, two stitched sources:

- KRS REST `https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P|S`
  returns the full registry extract for a company (name, address, capital,
  NIP/REGON, NACE/PKD, governing bodies). Personal-data fields (PESEL,
  surnames of board members) are masked by the registry itself.

- Biała Lista (white list of VAT payers)
  `https://wl-api.mf.gov.pl/api/search/nip/{nip}?date=YYYY-MM-DD` resolves a
  NIP / VAT number to the matching KRS, plus VAT status and bank accounts.

Identifiers supported:
    KRS    — 10-digit court registry number (primary).
    NIP    — 10-digit tax id; same value as the Polish VAT number with a "PL"
             prefix. Treated as both NIP and VAT here.
    REGON  — 9 or 14-digit statistical id; GUS BIR API would be the canonical
             resolver but requires a free key with manual approval, so we only
             accept REGON values that we can also pull out of the KRS payload.

Limitations (see docs/countries/pl.md):

- Name search is not exposed by the KRS REST API. The public web search
  (`wyszukiwarka-krs.ms.gov.pl`) sits behind a bot-detection layer and a
  session form, so it cannot be hit reliably with httpx. We raise
  `AdapterNotImplementedError` for `search_by_name` rather than ship a
  brittle scrape.
- Financial filings (sprawozdania finansowe) are published on
  `ekrs.ms.gov.pl/rdf/pd/` but the host enforces Incapsula JS challenges
  that block plain HTTP clients. `fetch_financials` returns `[]` and the
  CompanyDetails carries the public RDF URL so the UI can deep-link out.
"""
from __future__ import annotations

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
    Director,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_KRS_RE = re.compile(r"^\d{10}$")
_NIP_RE = re.compile(r"^\d{10}$")
_REGON_RE = re.compile(r"^\d{9}(?:\d{5})?$")
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _normalize_krs(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.isdigit():
        cleaned = cleaned.zfill(10)
    if not _KRS_RE.match(cleaned):
        raise InvalidIdentifierError(f"KRS must be 10 digits: {value}")
    return cleaned


def _normalize_nip(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "").upper()
    if cleaned.startswith("PL"):
        cleaned = cleaned[2:]
    if not _NIP_RE.match(cleaned):
        raise InvalidIdentifierError(f"NIP must be 10 digits: {value}")
    checksum = sum(int(d) * w for d, w in zip(cleaned[:9], _NIP_WEIGHTS)) % 11
    if checksum == 10 or checksum != int(cleaned[9]):
        raise InvalidIdentifierError(f"NIP checksum failed: {value}")
    return cleaned


def _normalize_regon(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _REGON_RE.match(cleaned):
        raise InvalidIdentifierError(f"REGON must be 9 or 14 digits: {value}")
    return cleaned


class PLAdapter(CountryAdapter):
    country_code = "PL"
    country_name = "Poland"
    identifier_types = [
        IdentifierType.KRS,
        IdentifierType.NIP,
        IdentifierType.VAT,
        IdentifierType.REGON,
    ]
    primary_identifier = IdentifierType.KRS
    requires_api_key = False
    rate_limit_per_minute = 60

    KRS_BASE_URL = "https://api-krs.ms.gov.pl/api/krs"
    WL_BASE_URL = "https://wl-api.mf.gov.pl/api"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.KRS_BASE_URL) as client:
                resp = await get_with_retry(
                    client,
                    "/OdpisAktualny/0000028860",
                    params={"rejestr": "P", "format": "json"},
                )
                resp.raise_for_status()
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
            capabilities={"search": False, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search not exposed by KRS REST (web search behind bot "
                "wall); filings on ekrs.ms.gov.pl behind Incapsula — both "
                "tracked in docs/countries/pl.md."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "KRS does not expose a public name-search API; the web search at "
            "wyszukiwarka-krs.ms.gov.pl is bot-protected. Use KRS, NIP, VAT, "
            "or REGON lookup instead."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.KRS:
            krs = _normalize_krs(value)
            return await self._lookup_krs(krs)
        if id_type in (IdentifierType.NIP, IdentifierType.VAT):
            nip = _normalize_nip(value)
            krs = await self._krs_from_nip(nip)
            if not krs:
                return None
            return await self._lookup_krs(krs)
        if id_type == IdentifierType.REGON:
            # GUS BIR API needs a free-but-manually-approved key; without it
            # we cannot resolve REGON → KRS authoritatively. Surface this
            # rather than guess, so the caller can fall back to NIP/KRS.
            raise AdapterNotImplementedError(
                "REGON lookup requires GUS BIR API key (not configured in MVP). "
                "Use KRS or NIP instead."
            )
        raise InvalidIdentifierError(
            f"PL supports KRS / NIP / VAT / REGON, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # ekrs.ms.gov.pl publishes RDF (Repozytorium Dokumentów Finansowych)
        # entries per KRS but the host is fronted by Incapsula and rejects
        # automated clients. Returning [] preserves the no-mock-data rule.
        return []

    async def _lookup_krs(self, krs: str) -> CompanyDetails | None:
        async with build_http_client(base_url=self.KRS_BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/OdpisAktualny/{krs}",
                params={"rejestr": "P", "format": "json"},
            )
            if resp.status_code == 404:
                # Fall back to the associations / non-profit register.
                resp = await get_with_retry(
                    client,
                    f"/OdpisAktualny/{krs}",
                    params={"rejestr": "S", "format": "json"},
                )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        return _details_from_odpis(krs, data)

    async def _krs_from_nip(self, nip: str) -> str | None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with build_http_client(base_url=self.WL_BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/search/nip/{nip}",
                params={"date": today},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
        subject = ((payload.get("result") or {}).get("subject")) or {}
        krs = subject.get("krs")
        if not krs:
            return None
        return _normalize_krs(krs)


def _details_from_odpis(krs: str, payload: dict[str, Any]) -> CompanyDetails:
    odpis = payload.get("odpis") or {}
    naglowek = odpis.get("naglowekA") or {}
    dane = odpis.get("dane") or {}
    dzial1 = dane.get("dzial1") or {}
    dzial2 = dane.get("dzial2") or {}
    dzial3 = dane.get("dzial3") or {}
    dzial6 = dane.get("dzial6") or {}

    podmiot = dzial1.get("danePodmiotu") or {}
    identyfikatory = podmiot.get("identyfikatory") or {}
    siedziba_blok = dzial1.get("siedzibaIAdres") or {}
    kapital = dzial1.get("kapital") or {}
    przedmiot = dzial3.get("przedmiotDzialalnosci") or {}

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(type=IdentifierType.KRS, value=krs, label="KRS"),
    ]
    nip_value = identyfikatory.get("nip")
    if nip_value:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.NIP, value=nip_value, label="NIP")
        )
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"PL{nip_value}", label="VAT"
            )
        )
    regon_value = identyfikatory.get("regon")
    if regon_value:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.REGON, value=regon_value, label="REGON"
            )
        )

    incorporation = _parse_pl_date(naglowek.get("dataRejestracjiWKRS"))
    dissolution = _extract_dissolution(dzial6)
    capital_amount, capital_currency = _extract_capital(kapital)
    nace_codes = _extract_nace(przedmiot)
    directors = _extract_directors(dzial2)
    rejestr = naglowek.get("rejestr")
    return CompanyDetails(
        id=krs,
        name=podmiot.get("nazwa", "") or "",
        country="PL",
        legal_form=podmiot.get("formaPrawna"),
        status=("ceased" if dissolution else "active"),
        incorporation_date=incorporation,
        dissolution_date=dissolution,
        registered_address=_format_address(siedziba_blok),
        capital_amount=capital_amount,
        capital_currency=capital_currency,
        nace_codes=nace_codes,
        identifiers=identifiers,
        directors=directors,
        website=(siedziba_blok.get("adresStronyInternetowej") or None),
        email=(siedziba_blok.get("adresPocztyElektronicznej") or None),
        raw=payload,
        source_url=(
            "https://wyszukiwarka-krs.ms.gov.pl/podmiot/"
            f"wynikiWyszukiwania?przedmiot=&numerKrsAdvancedSearch={krs}"
            f"&typ={'P' if rejestr == 'RejP' else 'S'}"
        ),
    )


def _parse_pl_date(value: str | None) -> date | None:
    if not value:
        return None
    # KRS dates are dotted "DD.MM.YYYY"; Biała Lista returns ISO "YYYY-MM-DD".
    try:
        if "." in value:
            return datetime.strptime(value[:10], "%d.%m.%Y").date()
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _extract_dissolution(dzial6: dict[str, Any]) -> date | None:
    wykr = (dzial6.get("informacjeOWykresleniu") or {}).get("dataWykresleniaZRejestru")
    return _parse_pl_date(wykr)


def _extract_capital(kapital: dict[str, Any]) -> tuple[float | None, str | None]:
    zakladowy = kapital.get("wysokoscKapitaluZakladowego") or {}
    raw = zakladowy.get("wartosc")
    waluta = zakladowy.get("waluta")
    if raw is None:
        return None, waluta
    try:
        amount = float(str(raw).replace(" ", "").replace(",", "."))
    except ValueError:
        return None, waluta
    return amount, waluta or "PLN"


def _extract_nace(przedmiot: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for block_key in ("przedmiotPrzewazajacejDzialalnosci", "przedmiotPozostalejDzialalnosci"):
        for item in (przedmiot.get(block_key) or []):
            dzial = item.get("kodDzial")
            klasa = item.get("kodKlasa")
            podklasa = item.get("kodPodklasa")
            if not dzial:
                continue
            code = str(dzial)
            if klasa:
                code = f"{code}.{klasa}"
            if podklasa:
                code = f"{code}.{podklasa}"
            if code not in codes:
                codes.append(code)
    return codes


def _extract_directors(dzial2: dict[str, Any]) -> list[Director]:
    out: list[Director] = []
    reprezentacja = dzial2.get("reprezentacja") or {}
    for member in (reprezentacja.get("sklad") or []):
        name = _format_person_name(member)
        if not name:
            continue
        out.append(Director(name=name, role=member.get("funkcjaWOrganie")))
    for organ in (dzial2.get("organNadzoru") or []):
        organ_name = organ.get("nazwa")
        for member in (organ.get("sklad") or []):
            name = _format_person_name(member)
            if not name:
                continue
            out.append(Director(name=name, role=organ_name))
    return out


def _format_person_name(member: dict[str, Any]) -> str | None:
    nazwisko = member.get("nazwisko") or {}
    imiona = member.get("imiona") or {}
    parts = [
        imiona.get("imie"),
        imiona.get("imieDrugie"),
        nazwisko.get("nazwiskoICzlon"),
        nazwisko.get("nazwiskoIICzlon"),
    ]
    joined = " ".join(p.strip() for p in parts if p and str(p).strip())
    return joined or None


def _format_address(siedziba_blok: dict[str, Any]) -> str | None:
    adres = siedziba_blok.get("adres") or {}
    parts = [
        adres.get("ulica"),
        adres.get("nrDomu"),
        adres.get("nrLokalu"),
        adres.get("kodPocztowy"),
        adres.get("miejscowosc"),
        adres.get("kraj"),
    ]
    joined = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return joined or None
